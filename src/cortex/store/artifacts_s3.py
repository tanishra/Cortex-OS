"""S3-compatible artifact backend (aioboto3). Prefix: tasks/<task_id>/."""

import asyncio
import base64
import json
import logging

import aioboto3
from botocore.exceptions import ClientError

from cortex.config import settings
from cortex.models import StepRecord
from cortex.ports.artifacts import ArtifactStore
from cortex.ports.registry import register
from cortex.store.artifacts import safe_filename

logger = logging.getLogger("cortex.artifacts.s3")


@register("artifacts", "s3")
class S3ArtifactStore(ArtifactStore):
    def __init__(self) -> None:
        self._session = aioboto3.Session()
        self._bucket_ready = False

    async def _ensure_bucket(self, client) -> None:
        if self._bucket_ready:
            return
        try:
            await client.head_bucket(Bucket=settings.s3_bucket)
        except ClientError:
            try:
                await client.create_bucket(Bucket=settings.s3_bucket)
                logger.info("Created s3 bucket %s", settings.s3_bucket)
            except ClientError as exc:
                # Another worker may have created it first — that's fine.
                if exc.response["Error"]["Code"] not in (
                    "BucketAlreadyExists",
                    "BucketAlreadyOwnedByYou",
                ):
                    raise
        self._bucket_ready = True

    def _client(self):
        return self._session.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name=settings.s3_region,
        )

    @staticmethod
    def _key(task_id: str, name: str) -> str:
        return f"tasks/{task_id}/{name}"

    async def _get(self, client, key: str) -> bytes | None:
        try:
            resp = await client.get_object(Bucket=settings.s3_bucket, Key=key)
        except ClientError as exc:
            if exc.response["Error"]["Code"] in ("NoSuchKey", "404", "NoSuchBucket"):
                return None
            raise
        return await resp["Body"].read()

    async def _list_keys(self, client, prefix: str) -> list[str]:
        keys = []
        token = None
        while True:
            kwargs = {"Bucket": settings.s3_bucket, "Prefix": prefix}
            if token:
                kwargs["ContinuationToken"] = token
            resp = await client.list_objects_v2(**kwargs)
            keys.extend(o["Key"] for o in resp.get("Contents", []))
            if not resp.get("IsTruncated"):
                return keys
            token = resp["NextContinuationToken"]

    async def write_step(
        self, task_id: str, step: StepRecord, screenshot_b64: str | None
    ) -> StepRecord:
        async with self._client() as client:
            await self._ensure_bucket(client)
            if screenshot_b64:
                try:
                    await client.put_object(
                        Bucket=settings.s3_bucket,
                        Key=self._key(task_id, f"step_{step.n:04d}.png"),
                        Body=base64.b64decode(screenshot_b64),
                        ContentType="image/png",
                    )
                    step.screenshot = f"step_{step.n:04d}.png"
                except Exception:
                    logger.exception(
                        "Failed to write screenshot for task %s step %d",
                        task_id,
                        step.n,
                    )
            await client.put_object(
                Bucket=settings.s3_bucket,
                Key=self._key(task_id, f"step_{step.n:04d}.json"),
                Body=step.model_dump_json(indent=2).encode(),
                ContentType="application/json",
            )
            replay = await self._get(client, self._key(task_id, "replay.json"))
            index = json.loads(replay) if replay else {"steps": []}
            index["steps"].append(step.model_dump(mode="json"))
            await client.put_object(
                Bucket=settings.s3_bucket,
                Key=self._key(task_id, "replay.json"),
                Body=json.dumps(index, indent=2).encode(),
                ContentType="application/json",
            )
        return step

    async def get_replay(self, task_id: str) -> dict | None:
        async with self._client() as client:
            data = await self._get(client, self._key(task_id, "replay.json"))
            return json.loads(data) if data else None

    async def list_steps(self, task_id: str) -> list[dict]:
        async with self._client() as client:
            keys = [
                k
                for k in await self._list_keys(client, self._key(task_id, "step_"))
                if k.endswith(".json")
            ]
            datas = await asyncio.gather(
                *(self._get(client, k) for k in sorted(keys))
            )
            return [json.loads(d) for d in datas if d]

    async def get_screenshot(self, task_id: str, filename: str) -> bytes | None:
        if safe_filename(filename) is None or not filename.endswith(".png"):
            return None
        async with self._client() as client:
            return await self._get(client, self._key(task_id, filename))

    async def delete_task(self, task_id: str) -> None:
        async with self._client() as client:
            keys = await self._list_keys(client, f"tasks/{task_id}/")
            # delete_objects accepts at most 1000 keys per call.
            for i in range(0, len(keys), 1000):
                await client.delete_objects(
                    Bucket=settings.s3_bucket,
                    Delete={"Objects": [{"Key": k} for k in keys[i : i + 1000]]},
                )

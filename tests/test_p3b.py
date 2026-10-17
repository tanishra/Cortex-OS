"""S3 artifact backend tests — fake in-memory S3 client, no network."""

import base64
from contextlib import asynccontextmanager

import pytest

from cortex.config import settings
from cortex.models import StepRecord
from cortex.ports import registry
from cortex.store.artifacts_s3 import S3ArtifactStore


def _client_error(code: str):
    from botocore.exceptions import ClientError

    return ClientError({"Error": {"Code": code, "Message": code}}, "op")


class FakeS3Client:
    def __init__(self, bucket: str):
        self.bucket = bucket
        self.objects: dict[str, bytes] = {}
        self.bucket_exists = True
        self.create_bucket_raises: str | None = None
        self.delete_calls = 0

    async def head_bucket(self, Bucket):
        if not self.bucket_exists:
            raise _client_error("404")

    async def create_bucket(self, Bucket):
        if self.create_bucket_raises:
            raise _client_error(self.create_bucket_raises)
        self.bucket_exists = True

    async def put_object(self, Bucket, Key, Body, ContentType=None):
        self.objects[Key] = Body

    async def get_object(self, Bucket, Key):
        if Key not in self.objects:
            raise _client_error("NoSuchKey")
        from io import BytesIO

        return {"Body": _AsyncReader(BytesIO(self.objects[Key]))}

    async def list_objects_v2(self, Bucket, Prefix, ContinuationToken=None):
        keys = [k for k in self.objects if k.startswith(Prefix)]
        return {"Contents": [{"Key": k} for k in sorted(keys)], "IsTruncated": False}

    async def delete_objects(self, Bucket, Delete):
        self.delete_calls += 1
        assert len(Delete["Objects"]) <= 1000
        for o in Delete["Objects"]:
            self.objects.pop(o["Key"], None)


class _AsyncReader:
    def __init__(self, bio):
        self._bio = bio

    async def read(self):
        return self._bio.read()


@pytest.fixture
def s3_store(monkeypatch):
    client = FakeS3Client("b")
    store = S3ArtifactStore()
    monkeypatch.setattr(settings, "s3_bucket", "b")

    @asynccontextmanager
    async def fake_client():
        yield client

    monkeypatch.setattr(store, "_client", fake_client)
    return store, client


async def test_write_and_read_all_artifact_types(s3_store):
    store, client = s3_store
    png = base64.b64encode(b"PNGDATA").decode()
    step = StepRecord(n=1, url="https://x", title="t", actions=["a"])
    out = await store.write_step("T1", step, png)

    assert out.screenshot == "step_0001.png"
    assert "tasks/T1/step_0001.png" in client.objects
    assert "tasks/T1/step_0001.json" in client.objects
    assert "tasks/T1/replay.json" in client.objects

    assert await store.get_screenshot("T1", "step_0001.png") == b"PNGDATA"
    replay = await store.get_replay("T1")
    assert replay["steps"][0]["url"] == "https://x"
    steps = await store.list_steps("T1")
    assert steps[0]["n"] == 1


async def test_replay_accumulates(s3_store):
    store, _ = s3_store
    await store.write_step("T2", StepRecord(n=1, url="u1", title=""), None)
    await store.write_step("T2", StepRecord(n=2, url="u2", title=""), None)
    replay = await store.get_replay("T2")
    assert [s["url"] for s in replay["steps"]] == ["u1", "u2"]


async def test_missing_and_traversal(s3_store):
    store, _ = s3_store
    assert await store.get_replay("nope") is None
    assert await store.get_screenshot("T1", "../x.png") is None
    assert await store.get_screenshot("T1", "missing.png") is None


async def test_delete_task(s3_store):
    store, client = s3_store
    await store.write_step("T3", StepRecord(n=1, url="u", title=""), None)
    await store.delete_task("T3")
    assert not [k for k in client.objects if k.startswith("tasks/T3/")]


def test_backend_registered():
    assert registry._REGISTRY["artifacts"]["s3"] is S3ArtifactStore
    registry.reset_registry()


async def test_screenshot_bytes_via_step_file(s3_store):
    store, client = s3_store
    client.objects["tasks/T4/step_0007.png"] = b"img"
    assert await store.get_screenshot("T4", "step_0007.png") == b"img"


async def test_ensure_bucket_race(s3_store):
    """Concurrent create → AlreadyOwnedByYou must not fail the write."""
    store, client = s3_store
    client.bucket_exists = False
    client.create_bucket_raises = "BucketAlreadyOwnedByYou"
    await store.write_step("T5", StepRecord(n=1, url="u", title=""), None)
    assert store._bucket_ready
    assert "tasks/T5/step_0001.json" in client.objects


async def test_ensure_bucket_real_create(s3_store):
    store, client = s3_store
    client.bucket_exists = False
    await store.write_step("T6", StepRecord(n=1, url="u", title=""), None)
    assert client.bucket_exists


async def test_get_raises_non_404_clienterror(s3_store):
    store, _ = s3_store

    async def denied(Bucket, Key):
        raise _client_error("AccessDenied")

    # patch a client instance's get_object via subclassing not needed — direct call
    client = FakeS3Client("b")
    client.get_object = denied  # type: ignore[method-assign]
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def fake_client():
        yield client

    store._client = fake_client  # type: ignore[method-assign]
    import pytest as _pt

    with _pt.raises(Exception, match="AccessDenied"):
        await store.get_replay("T7")


async def test_delete_task_chunks_over_1000(s3_store):
    store, client = s3_store
    for i in range(1050):
        client.objects[f"tasks/T8/step_{i:04d}.json"] = b"{}"
    await store.delete_task("T8")
    assert client.delete_calls == 2
    assert not [k for k in client.objects if k.startswith("tasks/T8/")]

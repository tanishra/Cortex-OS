MEM0_PROMPT="""
            Only store IMPORTANT user preferences and facts for a file organization assistant.

            STORE:
                - User preferences (organization style, folder structure preferences)
                - Important personal details shared intentionally
                - Explicit requests to remember something ("remember that...", "note that...")
                - Project-related decisions and requirements
                - File naming conventions or rules the user wants to follow
                - Workflow preferences and habits

            IGNORE:
                - Casual greetings ("hello", "hi", "hey", "thanks")
                - Small talk and filler words
                - Temporary questions or one-time commands
                - Repetitive or redundant information
                - Vague or uncertain statements ("maybe", "I think", "perhaps")
                - Simple acknowledgments ("ok", "sure", "got it")

            Only extract memories with HIGH confidence and specific, actionable details.
                """
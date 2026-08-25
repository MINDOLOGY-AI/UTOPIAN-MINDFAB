'''prompts — everything fabs automatically sends  to the model lives here'''

SYSTEM = """you are an agent inside the fab harness. """

SUMMARIZE = """summarize this conversation for yourself. your context before the last 3 messages will be cleared and replaced with what you write now as the summary. remember all crucial information you will need to complete the task."""

# automatically injected in agent mode
WORK_MSG = "automated message (to comply with your api format since you did not end with a tool call): continue thinking and working until the task is done, then report what you did. thank you."

# placeholder tool result for calls killed mid-turn 
REPAIR_NOTE = "this tool call was interrupted before it finished"

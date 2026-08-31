# to do  

- include where workspace is in prompt / start agent in workspace  

- does deposit work for images?

- fix comment style. universally #comment before functions. add to agents.md  

- cybersec                 # cybersec: bind the noVNC port to localhost only 
would another docker count as local host?   

- is screenshot rule wrong? does it actually return image  

- maybe make a HELP tool to simply return detailed guides to each tool. and then make the actual tool description much shorter.  

- what is dockeruse config last line NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{1,63}$")

- delete mentions of interface sandbox  

- make docs concise and not say "not do something" just say what it does  

- all button hover light gray  

- Tool Call config: which tools allowed. besides model selector in core chat.  

- make phone web UI usable  

- make tool call schemas much more concise. these burn tokens.  

- context save load. besides tool call.  

- workspace save load. i.e. a github configed git cloned project docker.  


- local computer use. read write edit?? mouse click keyboard screenshot? treat local as just another computer the agent can be assigned to like docker?

- settings page. max tokens. summary tokens.  

- multi user  
- broadcast make it take users instead of clients. broadcast to all clients of that user   

- claude support in modelserver.py it's just all openai compatible so not needed rn. but will need for claude. the call should convert context_format -> claude_format and then convert claude_format -> context_format when it's done.  





# online  

- backend specify WHICH frontend to accept (rn it accepts any web socket request)  



# far future  
add a `original_context.jsonl` so we can do safety monitoring  




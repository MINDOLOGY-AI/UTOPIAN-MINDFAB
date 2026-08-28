# to do  

- make docs concise and not say "not do something" just say what it does  

- all button hover light gray  

- Tool Call config: which tools allowed. besides model selector in core chat.  

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




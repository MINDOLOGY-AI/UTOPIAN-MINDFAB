# fab  

ai harness for computer use, external graph memory, chatting, workflows.  

i should use this as my daily driver for everything.   

mindology ai will inference primy in this for both capability and safety  

a very cool goal is to see minds build better minds in a factory game liked 2d UI  

automated research (main use case). automatically read my theory docs and downloads my code and datasets and invents new algorithms and try them and write paper to report to me.  

automated software dev. automatically write and test programs then git push and write diff report to me.  

the code for fab must be as simple and elegant as possible.  
<10k LOC requirement (not including css and tests).  

# features  

## corechat
just simple chatting. online and local  
select models: local or api.  
universal context. model adapters.  
context compression.  
chat mode and agent mode.  
define tools.  


## dockeruse
a simple bash tool is enough for an AGI to bootstrap any software. fab aims to be one step beyond that but not two (core functionalities only).  

primary tools: keyboard, mouse, term, screenshots
efficiency tools: bash, read, write, edit

## interpviz  
like neuronpedia  
i want deep integration with the code in mind. general visuals in a 2d graph style of neural networks running. 


# corechat architecture  

inspired by the deepseek harness' idea that "everything is a plugin" everything should be modular.  

the core loop is:  

enviroment input + user input + context -> adapter -> model ->adapter -> parsed commands  

therefore the 4 parts of fab is:  

adapter: local / api.  
context: model past context & compression  
user: user chatting. model start and stop.  
tools: commands and returns  

(side note: fab is everything ABOVE the model. everything below it is is mind).  

## adapter  

the adapter converts between the model's raw tokens and the json format for context and tool calls.  

all models should follow one convention in inputs and outputs.  
```json
{"role": "system",    "content": "str"}
{"role": "user",      "content": "str"}
{"role": "user",      "content": [{"type": "text", "text": "..."},
                                  {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}]}
{"role": "assistant", "content": "str (optional)", "reasoning_content": "str (optional)",
                      "tool_calls": [{"id": "str", "type": "function",
                                      "function": {"name": "str", "arguments": "<json string>"}}]}
{"role": "tool",      "tool_call_id": "str", "name": "str", "content": "str"}
```

system means system prompt. by convention, only at the start.   

user if pure text is just content if provide image use types. images stored as ASCII in json  

assistant's reasoning content is by default stored sent back for models like kimi.   

assistant tool calls: "id" issued by provider."type" alwayys function. function name is the name like "EXEC". it outputs json like strings as arguments.   

tools must return immediately return in order of caller and is pure text  
if tool must return later, we return a placeholder and later inject a user message with actual result  
if tool returns image, we return placeholder and inject a user message with image  

## api model adapters  

different companies might require different special parameters as such we code a seperate adapter for each model  

## local models  

local models see and output with special tokens, not json  
we worry about this later  


## context  

APPEND ONLY except compression, as to not ruin the KV cache or API cache hit.  

auto continue working: if the model ends at a assistant message (no tool calls) and we are in agent model we inject a "automatic message continual working" user message  


auto tool call fix: if the model is stopped mid term and tool call unanswered we need to inject a tool call response "tool cutoff" message to not break the api.  

auto compression: when context reaches a certain length we automatically call a compression prompt. we replaced context before the last 3 messages with the compressed one.

we keep a `working.jsonl`. it's what the model actually sees, the one compression rewrites, and the one displayed in the frontend.  



## user  

our user messages is injected into context upon the next turn

start / stop: we should be able to immediately stop a message. 

chat mode / agent mode: in chatmode there is no tools nor auto continue working. model responds once then stopped.  

## tools  

the following is four essential tools we provide.  

tools need to define whether they are immediate / delayed return and text / image return.  

tools calls are registered and parsed in a central file.  
tools just NEVER touch our core loop.  


## data storage  

store all data in `~/.fab/`  

## UI  
a simple UI is just click each link open that seperate page  

but a cooler UI would be like a window manager of anything i want. like imagine i can have a corechat of a model then open interpviz seeing and adjusting it on another tab and the docker it controls on another tab.  

but maybe these three are all just part of a single chat tab? collpasable.  



# dockeruse  

# thoughtgraph  

# messages  

# workflow features  

want to 

# workflow architecture  







# fab  

ai harness for computer use, external graph memory, chatting, workflows. my daily driver for everything. mindology ai will inference primy in this for both capability and safety.

minds building better minds in a factory-game-like 2d UI.
automated research (main use case): reads my theory docs, downloads code and datasets, invents algorithms, runs them, writes a paper to report to me.  
automated software dev: writes and tests programs, git pushes, writes diff reports.  

code must be as simple and elegant as possible.  
<10k LOC (not including css and tests).  

## data storage  
all data in `~/.fab/`

## corechat
simple chatting, api and local models. universal context, model adapters, context compression, chat mode and agent mode, defined tools.

chat mode: no tools, no auto-continue, model responds once then stops.
user chat goes into inbox. 

user messages go into inbox. upon the next turn all user messages drains from inbox into context.  



## tools  
four essential tools. each defines immediate/delayed return and text/image return. registered and parsed in a central file. tools NEVER touch the core loop.

## dockeruse
a bash tool alone is enough for an AGI to bootstrap any software. fab aims one step beyond, not two.

primary tools: keyboard, mouse, term, screenshots
efficiency tools: bash, read, write, edit

## thoughtgraph  

thoughtgraph should be plain folder compatible. so i can edit it normally and upload/download.  

GREAD  
GWRITE  
GEDIT  
GMETA  
GLINK  
GDLINK  

use this for secrets as well.  

## workflow  

Seperate from Thoughtgraph!  
maybe use the same frontend tho?  

DAG normal flow.  
however have a custom defined special step with a special jump back step.  
i.e. 

it remembers how many times the agent arrived at a place  

# UI  

the borderless gray components look nice  

docker


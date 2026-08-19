# fab  
my own AI workflow. i should use this exclusively for everything (doc writing, chatting, coding, video making) and not other chat / agent wrappers.   

i want to see minds build better minds in a factory game like UI.  

an external memory + a computer use wrapper + agent chat   

MUST BE < 10 K LOC. do not make this overcomplicated.  

# interface  

give models docker containers and computer use tools.  
essential tools: type, mouse, screenshot, term  
useful tools: exec, read, write, edit  
allows the definition of other tools in an openai format.  
auto summarization when limit reached.  

# secrets  

for account logins, github sshs and repo names, etc  
special programmable secrets:  
LLM APIs: mindfab uses this to call LLMs  
Compute Autorent (i.e. AutoDL): Tool Calls to rent compute  

# thoughtgraph  

a (.md) files graph viewer and accessm manager with purely a json and associated tools  
to be the shared external memory of myself and all the agents  
all knowledge should be supported by evidence and previous knowledge.  


# chat  

a group chat with users and agents for important messages and file sharing  
useful for sharing big files for ML like datasets and weights  

# workflows  

a to do app for the agents  
define custom repeated workflows like the ML workflow and Software workflow  



# open source CLI local version  

open sourcing makes sense — docker is really hard to secure.  
and we need to gather attention first  

we need a CLI version that can edit local files. start by forking Tau  

experiment with just a FLAT LIST view rather than graphs for CLI? no thoughtgraphs just folders and docs  

/agents (switchable into THEIR context)  
/settings  
/graph (Nice Graph display of thoughtgraph, toggleble view display)   
/todo (manage to dos)  
/chat (chat rooms)  



# paid online tier (later)  

then a paid tier where i rent AWS on their behalf: each paying user gets a docker to run all their agents. NO size limits or compute limits — way too difficult to enforce.  
the real draw is human-human collaboration: paid accounts can talk to each other and collaborate on thoughtgraph.  



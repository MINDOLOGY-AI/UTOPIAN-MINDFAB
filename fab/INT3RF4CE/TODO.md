# INT3RF4CE/TODO

## core abstractions
- agent = context + model + workspace. models are switchable; a context owns its workspace.

## agent management
- main page to view/manage all agents: API keys, logins, model selector, docker/workspace state.
- support local and remote models (AWS/local) so work survives laptop sleep.
- chat mode: don't alter system prompt; tell model it's in chat mode, no commands, pin conversation.

## docker & workspace
- docker commit to save state while keeping a clean base image.
- save/restore workspace alongside docker state.

## cloud  
- if user doesnt give any i auto rent AWS for them  
- also maybe need like a INT3RF4CE-server to serve local models on rented computers? this is switchable with cloud apis  

## tool system
- general tool-calling framework beyond docker: external devices, external tools, augment.

## integrations
- integrate with TH0UGHTGR4PH and tvdo to stop repeating instructions (style guides, skills, pinned reminders).
- `model_general` TH0UGHTGR4PH board for global prompts / style guides that outlive context.

## multi-agent
- multi-agent support with per-agent dockers.
- shared agent account in docker or in-program group chat protocol `<chat>[group][message]`.

## workflows & content
- self-testing workflows that verify their own work carefully.
- INT3RF4CE youtube series: one functionality per video, serial so future videos don't conflict.

## ui:

make docker screen hidable (expand chat). maybe when i press chat that just happens.  



## future:  

chat. make chat general, user AI or AI groups. make upload /downloading files part of chat.  


## future safety features:  

Context Monitoring: A different model reads the context (CoT and tool calls) and check if anything is dangerous

Network Monitoring: Decode and check all network calls and check if anything is dangerous BEFORE letting the call through  

Activation Monitoring: Use Mech Interp to interpret inner activations to see if model is


## future workflow page  

add a main page. where i can like have many agents, define groups, and workflows (who review who does what). like imagine graphically clicking and like copying a model + prompt blocks + docker into an agent and dragging it into a group chat.  

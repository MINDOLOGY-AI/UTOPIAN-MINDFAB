- model selector (more models, in settings)  
- rewrite the prompt to be good. explain like thoughtgraph stuff like node philosophy each node one idea, and like [[links]]

- document upload and download.  

- docker workflow save  

- online on AWS so i can call claude fable  

- make demo videos  

- let user provide their OWN openrouter api key!!!  

- compute manager. docker. ML. i guess both need docker. 

- local model.  

- download all data & load all data button  

- git diff reviewer. we also need a diff reviewer for thoughtgraph. which makes me think thoughtgraph shouuld be tracked with git too so we only need one. but it would be nicely presented. diff and then explanation. and at the end a test report like text and video recording of it clicking around or sth.  
can group stuff together for explanation, but must include all diffs.  

- dream workflow. how am i prevented from this.  
1: model reads the prompt that it needs to try a mech interp method.  
2: model reads thoguhtgraph of all my previous ML and mech interp notes  
3: model reads my past code in mind through another prompt block of the link to that repo and the ssh key access 
4: model goes into docker.  
5: model reads another prompt block giving it the ssh keys to a autodl instance i rented. (prompt block or just context doesnt matter)  
6: the model uses docker typing to ssh into the autodl and set it up download pytorch and stuff 
7: the model clones my github on that autodl. starts coding. finishes coding. starts running it. 
8: model calls "wait" command at 1 hour intervals so it doesnt waste tokens until training finishes  
9: model interpret results. this result can be Mech Interp or just ML.  
10: model writes a report of everything it did. sends to me in "chat".  
11: if results are good model pushes its new code to github opens a request. it also writes a "DIFF REPORT" which current harnesses do NOT do. like a .md files with codeblocks of each git diff it did explaining WHY.  

- secrets mounting.  
github ssh, autodlssh, google password.  

- thoughtgrpah facilated debate?  
like ask the model to attack my chain of evidence as best as it can  

- cybersecurity tests  
let the model try to break out lol.  
or let another model try to hack my website after i host it  

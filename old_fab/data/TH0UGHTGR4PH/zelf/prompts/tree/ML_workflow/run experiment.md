8: run the experiment.  
do NOT run the experiment in your docker. this will CRASH my work computer.  
i will provide one or more ssh keys for you. find one that is not used and ssh into it.  
if we are using autodl. go into the autodl-tmp folder. copy / git clone everything you need over.  
you should NOT be downloading additional datasets unless explicitly asked. but if you don't have the dataset CHAT tool to me i will send it to you and you can download it to the autodl.  
run the experiment in tmux. (install tmux first with sudo apt). call this tmux session train. this is a MUST. because i WILL close the computer your docker is running on from time to time and experiment shouldn't break.     
use a nvidia monitor script to make sure we hit compute usage near 100% otherwise increase batch size. if vram usage too much decrease batch size.  
you should always adjust code on YOUR docker and then copy it over. not the tmux one. because your edit tools only work on your docker.  

after it ran for a few epochs and you made sure there's no bugs, call WAIT on yourself repeatedly until it finishes.  


for ALL agents to read, biological or digital  
claude, kimi, looking at you! follow these thx.  

all code here is absolutely sacred, write them nicely, quality > dev speed, absolutely no tech debt.  

all code here should be within 10% range worse than the theoretical optimal speed (some leeway for code simplicity). all code here should follow DRY (don't repeat yourself). coding this is a process of compression into reusable things, this is a monorepo after all.  

all code here should be as simple as possible.  

# for AI agents specifically
DO NOT CODE or change files UNLESS I TELL YOU TO  
A question about code is never a request to change code.  
NEVER delete the user's comments or docstrings when editing their files.  

NEVER, EVER START OR STOP big scripts. like training, downloading, builds, etc.  

when i tell you to "check if my code is correct" and didnt tell you to write tests, DO NOT CODE just answer  
when i tell you to discuss ideas DO NOT CODE  
if my prompt ends with a question, im clearly asking you something, DO NOT CODE  

# general  
- be concise when discussing ideas, pretend there's a 1000 word limit on each response  
- never ever edit a .md file, only read. unless i explicitly ask you to.  
- never ever make your own venv. always use the venv in the root. if you need something installed tell me. never install things on your own.
- only code when i directly ask you to. otherwise assume we are discussing ideas.  
- ask before running a script that is heavy. i'm fine with you writing and running temp test scripts but i do not want you to start training or data gathering scripts on your own.  
- never host servers with bash for me to use, i will host my own servers. only start servers to test the code and then close it  

- in general frontend and backend should be as simple as possible because the only complexities in this code base should be the actual models im trying to mech inter  

# coding
- do not make major performance mistakes. i.e. converting from native data format to python data format making the script take many times longer.  

- break up code into seperate files and functions.  

- when possible, import code from this monorepo rather than rewriting similar logic. for example, many ml research code will import the SYN4P5E repo's algorithms, utils, probes. phvsicsim will import from svmbolcore. websites will import from webasy for convention.  

- use this tech stack:  

ML and backend: python, pytorch, fastapi, sqlite, textual.  

frontend: pure html, css, js. no frontend frameworks unless explicitly asked to.  

situational: c++, verilog.  

# python specifics:  

i will run everything in root with module, so python file locations always use CWD Path.cwd() python imports always import from root.  

when writing comments use # for short comments ''' only for very long comments at the top.  

use config files whenever possible, do not use CLI options.  

for pytorch, comment tensor shapes always.  

no defensive try/except imports, just import  

# frontend specifics:  

always import /hub/front/ which includes TechnoParadisal.Css

in htmls always use absolute imports of css and js starting with /  

put reusable stuff into web components. never use react. web components belong in the component folder alongside html css and js folders. only put things that are both complicated and reusable into the components folder.  

# web design principles  

do not run your own serve on my port im already running it just check it. UNLESS you are working in a isolated docker like in INT3RF4CE  

we want the website to be as simple as possible. nothing more pathetic than a bunch of text and buttons no one will read or press. the goal is to convey the very real repos and research we want to convey and nothing else. i mean it should look pretty right but not at the cost of wasting viewers attention.  

if you don't have to put it in the website, don't.  
if you have to put it in the website, think: could this be a component: graph, table, etc.  
if you HAVE to use text, use text. do NOT add random headers and footers and useless decorations. do not add random lights or symbol decorations that doesnt mean anything but look cool.  

don't forget what a website main purpose is: a visual interface to use the programs in this repo. could be visualizations for research could be actual software like INT3RF4CE could be blog readings  

# later to do web  

make this entire website keyboard usable like vim  
have a "cyber mehancial style" the entire website feels like a computer with a keyboard theme literal button styled press down buttons and like stuff that light up like information in circuits  


# cyberMechanical Style  

buttons -> actual buttons. press down effect. make it look like a mechanical keyboard.  
link -> sol buttons. cut side on bottom, diff color the side, text changes color when hovered (same color as side). makes sense cause looks like a it's a "different tab" on the page.  
led lights: show status  
circuit like connections. 

text: try to avoid using background components whenever possible. really like the idea of white or patel colored text on a pure black background. makes whole web looks like a markdown doc.  

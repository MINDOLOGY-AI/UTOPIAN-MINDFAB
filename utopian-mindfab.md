utopian mindfab

written concisely as a technical doc. aimed to identify the wants and features and designs.   

# the 5 parts

the repo is 5 folders. each part keeps its own data/ and weights/ when it needs them.

- **fab/** — the software layer above everything. augments, hub, INT3RF4CE, TH0UGHTGR4PH (+ drawio, thoughts legacy) — eventually merged into one tab (this doc, see VERSIONS). fab/data: auth, INT3RF4CE, TH0UGHTGR4PH. fab/logs.
- **mind/** — neural computation. SYN4P5E, EV0K3, D4TA5TEPS, interp_journey, original_research, PRIMY. mind/weights, mind/data.
- **symbol/** — symbolic computation. nothing here yet.
- **robot/** — hardware. what this ultimately controls. nothing here yet.
- **writing/** — the texts.

# what i want

imagine visualizing a digital mind building a better version of itself. all these repos tied together in a single 2d plane: agents, utopia plans, mindology theory, SYN4P5E, D4TA5TEPS, EV0K3, intvrpviz, etc.

- i want this to be the software bound and enabler for a model, so i can identify the algorithmic limitations. powerful enough to IDENTIFY why current models cannot be primy (we are not using elvish genetic engineering as a benchmark).
- i want a software docker for computer agents to run and test their own outputs, software wise.
- i want a prompt manager: a single set of software rules and guidelines, my own coding style. hierarchical stepwise functional or whatever.
- i want TH0UGHTGR4PH. seeing all my symbolic knowledge and writing mindology. md docs and edges.
- i want the NAS loop towards primy.
- i want node types of the world state towards utopia:
  - world state + actuator + model -> new world state
  - world state + actuator + model -> new actuator
  - theory -> algorithms -> test -> theory
  - algorithms + data + train -> model
- i want automatic mindology research agents at the end of mech interp, constantly using their broad internet knowledge and math skills to expand and test my mindology framework.
- i want to clearly see dependencies. what is parallel, what is sequential — as parallel as possible. i want to operate on the edge of mindology, not waste time writing repetitive code.
- i want to see the status of every agent.
- i do not want to re-explain myself, my research, or my code to a model over and over. it should just read the corresponding TH0UGHTGR4PH nodes and find out.
- i want benchmarks. easily accessible benchmarks.
- i want to publicize this and gain money and attention, for compute and coworkers.
- the model will have its own TH0UGHTGR4PH board and i will have mine. it should be able to write down every single thing it knows in TH0UGHTGR4PH and then use the internet to check it.
- writing things in thoughtgraph to communicate with a llm is better than just chatting because it is clearly LTM not STM and you can build ideas on top of each other.  


# features

note: anything marked (later) is for later sessions — do not implement yet.

## boards and style
pure 2d boards. no 3d. can't see vertical edges. use the y axis to denote topics.

simplistic grid style for everything. every element is 2d, defined by height, width, and location (project, z, x, y). z is the abstraction level — maybe math is the highest, particle physics the lowest. collapsible folder groups. or maybe just all 2d with multiple boards, colors for topics.

we are always in SOME function. like the ones lighting up. whether green or white. and the model can called "fab-actions" to move along. and the users maybe can mark themselves as a purple node?   


## TH0UGHTGR4PH
two views: by content (what part of the world it models), or by stableness (how evidence-supported it is).

TH0UGHTGR4PH use the functional style too. like support function, etc.  

knowledge, evidence, theory.

## augments
todo: an overall life path graph from current actuators to future plans, to mindology.md, primy, utopia. TH0UGHTGR4PH reaching towards primy. maybe an actuator tab. with TH0UGHTGR4PH, thoughts lead towards thoughts; in actuatorgrvph, actuators lead towards stronger actuators.

DAG. parallel and sequential.

chat: like groups for the model?

## INT3RF4CE
what makes compute usable. runs agents. like "factories".

## computer nodes
- main nodes (for dockers)
- compute model nodes (for local models)
- compute nodes (for ml experiments and whatever else heavy programs)

## permissions
pub: hub, INT3RF4CE, intvrpviz. private: SYN4P5E, D4TA5TEPS, EV0K3. like a company where different employees have different access levels.

agent write access: the commercializable audience-facing parts (INT3RF4CE, augments, hub, TH0UGHTGR4PH code) agents should NOT write unless explicitly asked. their main goal is contributing to TH0UGHTGR4PH (mindology board), SYN4P5E, D4TA5TEPS, EV0K3.

## scope (stage 1)
we do not care about: acquiring compute, robotics, recursive hardware self improvement. even money and fame are side effects. the main effect of this repo is writing mindology in TH0UGHTGR4PH.

## design principles
the division of thoughts vs code vs whatever is sort of arbitrary. the measure of good vs bad thoughts is sparsity and recon: how well it compresses reality.

design software starting from what i directly, simply want to do, then make it more complex after. it should be as simple as possible, as software should be.

## later ideas
- self-hosted git for the whole repo? for diffing, branching, agent collab.

# general workflow and node types

## workflow
different pages have different workflows, but fundamentally each is a combination of prompt, context, model, and tools. design the specific ones first, then see how to generalize.

a lot of things follow the same structure: future tasks depend on past tasks, later knowledge depends on previous knowledge, actuators require previous actuators. the previous tasks a task depends on, or the previous knowledge a theory depends on, becomes context.

open questions: git push? approval?



## node types
different node types get different colors.

by time (maybe this is just the x axis):
- future tasks
- working tasks
- past tasks

by data type:
- .md files
- code repos & commits

by substrate — what should be neural and what symbolic? at the end of the day only correct outputs matter. the point of software is to reduce complexity:
- symbolic (white): software, file sharing, data
- neural (green): agents, ml training, humans
- physical (blue): cheapy


## the pages
- the todo / agent page (seeing what is parallel is important): future tasks
- the TH0UGHTGR4PH mindology research page
- the software page (build, test, review) — see software workflow
- the NAS model page — see ML workflow

## views and control  

allow a fab view, the graph view with everything, and also a more intuitive agent list view  

allow intuitive mouse control and a toggleble vim like pure keyboard control   

need autoplacement for DAGs. cause to a model maybe it is just straight up objects and functions.  

# software workflow and hierarchical functional style

the general workflow is simply the model does something, enviroment responds, model evaluates. repeat.  
works for coding. 


## step wise functional
graph everything as functional:
- inference(input, model) -> output
- training(input, model) -> model

this way i can differentiate models at different stages. mech interp is like opening a big function and seeing what the smaller functions do.

docker and context are hard to call functional. so: step wise functional — within one left-to-right software graph it's functional, but i can draw special arrows back into docker and stuff that happens AFTER.

step wise functional is great for digital neural networks!

## hierarchical coding
rather than codeflow: organize functions by hierarchical levels, so on a broad scale everything is obvious. still step functional style — maybe the top file is a single program step, and user inputs are just command signals in those steps.

levels in the file name, l0 l1 l2 or whatever:
- l0: one abstraction. the factory way folded. written based on the feature doc — each function specified what it does.
- l1: slightly expanded.
- l2: everything below.

when functions get complicated or share features, push them down an abstraction level so they can be reused.

maybe codeflow can still be part of the graph too — that's how we literally tie the code in with the graph and the todo.

# ML workflow

SYN4P5E, D4TA5TEPS, EV0K3: what the models call from and write to as a requirement, managed with git.

benchmarks, dataset, theory, algorithm, training, probes are tied together. example: after it learns to solve derivatives, i should be able to interpret how it did that — and from the probes derive the theory for the next benchmark. TH0UGHTGR4PH is tied in too: the model is gradually learning my TH0UGHTGR4PH.

the ML workflow is.  
from aesthetics define the task we want done  
from task identify the capability and benchmarks  
create dataset similar but not overlapping to benchmark  
create algorithm and training according to our theory
start training  
evaluate by benchmarks
make probes by theory  
try to interpret completely  
update mindology theory  

this is "neural guided neural architecture search" i guess.  


## the NAS model page
1. identify capability we want
2. create the benchmarks
3. build the algorithm and specs from mindology theory
4. gather the dataset
5. train
6. test — IF passed, continue; if not, try a different step 3
7. probes from mindology theory
8. see interp — IF completely interpreted, continue; if not, go back to step 7
9. safety test — IF passed, continue; if not, go back to step 3 or 4
10. replace current agent model with this one

## to dos are benchmarks
terminal utopian is really just a mind that fulfills increasingly difficult benchmarks: from math questions to building robots to elf engineering to self replicating probes.

## continual learning
with continual learning, the TH0UGHTGR4PH is supposed to be internal to the model — perhaps even interpretable through probes.

## thoughtcore
kinda like thoughtcore: a model that has read TH0UGHTGR4PH will understand everything about me and this project.

## intvrpviz
how this ties to mindology: intvrpviz is like expanding the folder of a model, seeing its internal mechanisms.

## local model?
one small model (flinty?) runnable on a 5090, finetuned towards ML, math, code, and mindology rather than knowing all these random facts.

## rsi? (later)
maybe run a local model with EV0K3, connect it to INT3RF4CE so it can literally use our own research to make itself better. given our current lack of compute and research i doubt it, but it would be cool.

RSI improves on two axes: 1) benchmark scores 2) how small the model / training time is.

and then just a model calling "model select" when it thinks it's done.

## arc agi 3? (later)
maybe this harness with a good workflow can solve arc. it is asking questions and testing after all.

# VERSIONS

we DO already have stuff. so v0 is what exists, and each version after is small and shippable.

## v0: what exists
- hub: one fastapi process (port 2121) mounting everything. auth (scrypt, session cookie), technoparadisal theme + cyber components.
- TH0UGHTGR4PH: boards of md docs + folders as real files on disk, typed edges (relate / support / contradict), wikilinks, grid snapping, version snapshots, per-user storage. WORKING, dogfooded.
- INT3RF4CE: docker agents (xvfb + chromium), one ws protocol, kimi adapter, auto screenshot feedback, context summarization. WORKING, dogfooded.
- SYN4P5E: transformer primitives (GQA, RoPE, MLP, RMSNorm) assembled into full olmo2, train helpers, SAEs (jumprelu, slabcone), static analysis probes.
- EV0K3: OLMo2-1b loads 1:1 from HF weights, chat_local validates the from-scratch model, static analysis ran.
- interp_journey / function_approximator: full train -> visualize web pipeline, mounted in hub.
- D4TA5TEPS: readmes only. PRIMY: empty dir. augments: readme only.

## v1: the general board
extend TH0UGHTGR4PH from "md docs only" to typed nodes: doc, code (git ref), weights, dataset, task.
node state is derived, never edited: future (inputs missing), working (agent attached), past (output committed).
this is the "one general workflow board with everything".

## v2: agents on the board
INT3RF4CE agents attach to task nodes. agent context = its inbound nodes (no more re-explaining). agent status visible on the board. prompt manager = the single set of software rules every agent carries.

## v3: the views
todo / agent page: tasks with missing inputs, x = dependency depth, so parallel lanes are visible.
TH0UGHTGR4PH two views: by content and by stableness.

## v4: benchmarks as nodes
D4TA5TEPS benchmarks + eval reports as nodes. the NAS 10-step loop as a reusable board template. the full ML workflow lives on the plane.

## later (do not implement)
intvrpviz as expanding a model's folder. thoughtcore. local model (flinty on a 5090). rsi + "model select". arc agi 3.


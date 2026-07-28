# a concise doc.  

get the ideas down  

# layout  
2d boards, multiple boards.  
folders and nodes. autoplacement?  

grids. nodes and folders on there. functions as circles at intersections.  
i will call everything "nodes". there are three types of nodes: objs, funcs, and folders.  
all edges must be between objs and funcs and are directed.  

# memory  

STWM: short term weight memory (KV cache)
STEM: short term external memory (context)
LTWM: long term weight memory (weights)
LTEM: long term external memory (thoughtgraph)

# node types  

allow each individual users to define and color code types!  

my nodes:  
axioms, definition, theory, evidence, hypothesis  
algorithms (and training, peripheries, probes), weights, datasets, benchmarks  
actuators, world states, aesthetics, feature_doc  

# time types  

only for objs not functions or folders  

done, doing, to do,

maybe color coded in 

# function types  
allow each individual users to define and color code types!  

note the ENTIRE docker agent is ONE function node that can be clicked to be expanded!  

my functions:  
support, reject  
inference, training  
calculating (not currently used, large scale symbolic computation)  
use

# special obj nodes  

the idea is each agent IS A obj NODE!  
like a model is a mode right.  
to give you an example. we have a theory node of say ML theory. it goes into a support func node into a say code link node. an agent is an obj node a special kind also connected to the support func node. symbolizing that IT IS like DOING THE sort of action that is supporting what that like it is the DOER of that function.

## compute nodes  

some stuff are marked as compute nodes in contrast of say "theory nodes".  

like agent nodes? which is like a docker. like i.e. a docker writing algos from theory.  

and a like a ML compute node. doing training or eval. is like using dataset and a algo node to make weights.   



# compute window  

need someway to clearly visualize 1: computers 2: what they are running: docker / ML experiments/ local models

one computer can be running multiple things  

need elastic computer renting and docker copying.  

# graph actions  

create  
-node {name, obj/func, specific_type}
-folder{name}
-edge{obj, func}

read  
-node {name}
-all_connected{name}

update  
-node {name, content, type}
-node_folder {node_name, folder_name/none}

destroy  
-node {name}
-folder {name}
-edge {obj, func}

move  
-node {func_name}

# prompt management  

prompts are perhaps a kind of obj? with the type "prompt"  

but we do need a seperate prompt management window when creating a agent.  

# agent access management  

we have to give agent a list of access right settings to 
graph actions (whether it can create / edit or just read, what it can read)  
compute usage (what it can rent)  

an agent slot is just a bunch of connected prompts and thoughtgraph nodes it does not HAVE to be filled with an agent.  

additionally within the slot there is context and model type and things. specified in interface.  

# workflow  
a workflow is essentially a bunch of pre arranged docs and functions with prefilled types and partially filled content, and prompts.  

this can form a loop.  

## the software workflow  
1:  
software prompt + design doc + github link   
(writing the code then running)

2: 
review prompt + design doc  
(reviewing the code)
Decide: go back to 1 or advance to 3

3:
PR prompt
(push and write report)  
commit git, open the github pr and write a detailed report explaining each git diff

after this it is done  

## the ML workflow 

1:
Aesthetic docs + theory docs -> Identify capability we want

2:
Capability -> identify benchmarks. write scripts to gather benchmarks. and also gather datasets.  

3: from theory docs write the algo and training and identify previous weights we can use

# git.  
we track everything in git. from code to graph. so we can have versions saved.  
maybe we self host later but for now we use github.  


# common workspace?  
maybe we need a common workspace for datasets and weights so git links actually mean something?  
we definitely need file uploads and downloads somehow in chat other than git  



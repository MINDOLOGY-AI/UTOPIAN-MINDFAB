# purpose  

to gain all geometric intuitions about neural networks possible to gain.  

to completely understand the internal shape transformations, limitations by size, and training dynamics  

it's best to merely use geoemtry to gain intuition to think in "numerical" terms becaues 2d and 3d is visualizaiton but 2560d isn't.  


# training  



allow setting epoch and lr. show the lost curve (plotted in svnapse). delete weights after. save everything in data/interp_journey/function_approximator/  
allow setting number of layers, and inner dimensions of each layer. (default relu after each). use the svnapse mlp model.  
for 1d to 1d: draw a line. export in pure 1 and 0 (either drawn on or not) (take highest point for a given x since its a function). pure x to y sample some points unit distance.  
for 2d to 3d: draw random colors, export in rgb values.  

for the mlp 2d 3d 2d. allow drawing any number of input and output pairs. will be added to training data. after training. show the predicated pair for each input in a similar color in the same output window so i can compare.  
also for 2d 3d 2d after training in input plane add a draggable vector that i can drag, and it will show the corresponding output in the output tab.  

by the way each like type 1d 1d, 2d 1d, 2d 3d 2d, is a different html. each seperate stuff inside it is a different window component.  

# geometric visualizations:  

just 1d 1d and 2d 1d and mlp (2d 3d 2d) for now.  

## hyperplane view of a neuron  

hyperplane view: sweep inputs, show what that neuron outputs. in a 1d->1d, it would be a simple 2d graph. in high dimensional if the input to the neuron is nd the graph would be a n+1 hyperplane. if there's a relu after show only the version with the relu after, with a hinge.  
## input output hyperplane  

also show how each neuron contributes to the final output. if output is 1d this is 1 thing, if nd this is n things.  
if it's a middle layer, sweep across the earlier layers and feed their inputs into this layer. do a forward pass to completion. freeze the nonlinear (relu turning on and off). then pass the targetd neuron individual output in with the frozen nonlinearity and get the final output  

## literal neuron  
for the 2d 3d 2d you need to show 2 more windows. first a 2d window of the encoder layer (first layer) rows. just the literal neurons as vectors. second a 2d window showing the columns of the decoder (second layer). i should be able to drag these vectors. it will record the values, send it back to the backend to set the model weights, recompute everything else, send to the frontend, render.   

## space shift:  
for 2d 3d 2d show the "piecewise space shift" in another window. the decision boundary of each neuron cuts the input space. each space will be different colors, and we will show what it turns into like that whole space post forward pass. do this by using the same colors. dont just show the edges, but like maybe draw some straight lines inside like a grid in the input space and show how they slant in the output. maybe just like a square in it with 4 sides different colors, since within a non linear region it is linear, i can just with a single grid see the shift and scaling.   








# tech stack  

html canvas 2d  
pytorch  
fastapi  

# repos used  

all web components put in hub  
all training and model code use svnapse  
do NOT code these yourself  

# to do later ( do not code now)  
nd to nd parallel coordinate plot  
3d to 1d  

THOUGHTGRVPH

# to do:

api for AI to use  
integrate into intvrface (along with chatting collab)  
a "doc into version


# purpose  
md file organizer

my entire brain should be roughly written in here.
notes for all my knowledge. and expanding them with thoughts.  
from world model (math, physics, neuroscience, etc.) to aesthetics (utopia, thoughtcore, etc.) to life paths and to dos to current actuator status.  

ultimately it is hard for symbolic software especially just a 2d grpah to approximate how the neural brain learns information but this should make it as easily as possible for me or ai to quickly learn information recorded in it.  



# features:  

- board of draggable nodes: docs (.md rectangles) + folders (ovals). no auto layout, positions remembered.
- everything is real files in `thoughts/thoughtgrvph/` (gitignored): folders = dirs, docs = .md files, disk mirrors board. one json for positions/edges: `thoughts/thoughtgrvph/<board>/meta.json`.
- double-click doc = expand + resize. shows rendered markdown, click text = edit raw, click away = render again.
- double-click folder (or sidebar toggle) = expand into a container box wrapping its contents. nesting tints alternate blue/yellow.
- selected folder = pink. add doc/folder goes inside it. drag onto it = move in. drag out of a non-selected folder = move out one level.
- edges: add edge button, click two nodes. three colors (gray relate, green support, red contradict) picked in sidebar. selecting a node highlights its edges.
- sidebar: folder tree + edge color picker.
- versions: toolbar panel, save/delete/restore full snapshots of `data/` into `data/versions/`.
- hyperlinks: `[[doc title]]` in any doc. renders as a link, click = jump to that doc. auto-creates a gray edge. dangling links render red. doc titles globally unique, renames rewrite links everywhere.

layout rules:

- double-clicking a node keeps its top-left corner in exactly the same place.
- expanding shifts everything below the node down by the height increase, and everything to the right of the node right by the width increase. diagonal nodes get both shifts.
- nodes are processed top-left first, so earlier nodes stay put while later expansions make room around them.
- descendants and ancestors of an expanding node are not moved; they belong to its subtree.

serving: mount `thoughtGrvph.back.api:app` in `hub/back/app.py` and visit `/thoughtgrvph/`. it is no longer served standalone.

board delete is permanent: the 🗑 button removes the board from the menu AND deletes `thoughts/thoughtgrvph/<board>/` (nodes, edges, versions, everything). a confirmation popup warns you first.

tech stack:  
frontend:  
pure html css js (+ marked.js cdn for markdown)  
backend:  
fastapi python  


# future to dos:  

ideally ALL my thoughts should be here. so i need to make this include a to do app, a MCTS tracker  

this needs to be made into a viewable website, a monetizable product, a social media, a ai colloboration tool. it doesnt need to be complicated but it needs to be robust and online.    





# purpose
the main website of MINDOLOGY AI  
serve our model, products, research, visualizations, ideology
make money. one subscription for all the monetizable stuff. one website i can advertise in my videos.  
directly served on mindologyai.com  
also contains the TechnoParadisalTheme.css and web components for ALL web to use throughout this mono repo  


# features  

the website will show to the world a selected collection of company code not all.  

the stuff needs to be on the site are stuff we want the public to use (for their own benefits), to pay us for, to read. or interactive visualizations that cannot fit in TH0UGHTGR4PH.  

particularly what we show is coherent: 
the model (pvvr for now cause we are poor, primy when we're rich)  
the mech interp visuals and original research and TH0UGHTGR4PH notes that lets us create and align the model  
the wrapper the model or team of models can use  
the symbolic tooling to complement the model (as tools or training envs)   
augments for the model to use (or team of models)  
writings, which can be used to prompt the model.  

eventually when we are good enough we will pull TH0UGHTGR4PH down and be private, and all code from github, all models from access, etc.   

# technoParadisalTheme  

every color should be one of my favorites  
like a efficient techy and dreamy and soft look

# web components collection  

this is also a "hub" for our other web code  
including components with any sort of reusability whatsoever  
from links buttons and lists to fit our cyber mechanical style  
to stuff like 2d and 3d canvas draw and renderes

# auth

auth for the entire site. will do payment later.

one login for everything. site content is public/read-only; individual apps (e.g. INT3RF4CE) require login.

code: hub/auth/ (store + routes). data: data/auth/ — users.json, sessions.json (gitignored like all of data/).

- passwords: scrypt (stdlib hashlib) with per-user random salt. plaintext is never stored.
- sessions: random 32-byte token (secrets) in sessions.json {token: {user, expires}}. cookie `mindology_session`: HttpOnly, SameSite=Lax, 30 days. server-side sessions, so revocation = deleting one line.
- routes (hub/auth/routes.py): POST /auth/register, /auth/login, /auth/logout, GET /auth/me. login/register are rate-limited per ip.
- frontend: `<auth-box>` web component (hub/components/AuthBox/) — top-right login/register/logout for any page that includes it. fires an `auth-changed` event on login/logout.
- apps gate themselves: INT3RF4CE checks the session cookie on the websocket handshake and blocks everything until login.

later: payment = a `paid_until` field per user + a payment webhook. auth itself doesn't change.





# ramblings  

use a multi page site and lazy loading to make it infinitely expandable and not slow  

(since i bought a bunch of domain names might as well have like extra links to them until they expire but don't rely on them advertise the main site)  

each individual website should be able to be served individually but the main one should have a link to all of them and they should all be sort of reachable from mindologyai.com/sth  

use webcomponents, do not use react, since the only thing hard to understand in this repo should be the actual models. and because the complex stuff are graphs and tensors not dashboards.   



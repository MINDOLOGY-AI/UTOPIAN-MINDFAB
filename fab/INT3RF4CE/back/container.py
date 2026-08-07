"""
Docker wrapper for agent containers with xvfb + noVNC.

noVNC flow (for human monitoring in browser):
    x11vnc inside container on port 5900 (VNC protocol)
    websockify on container port 6080 translates everything between http and tcp WebSocket <-> VNC and forwards to 5900.  
    docker -p (publish) makes host_port a transparent pipe to container:6080
    browser connects to localhost:host_port/vnc.html — same as talking to container:6080
    multi-agent: each agent gets a different host port (6080, 6081, 6082...)
    this frontend to docker host varied <-> docker 6800 <-> docker vnc 5900 is only used for vnc for now.  

Usage:
    c = Container("usr", "agent_1", novnc_port=6080) #novnc port on host
    c.start()
    # open browser to localhost:6080/vnc.html

    c.screenshot()
    c.type_text("hello")
    c.click(1)
    c.run("ls /home")

    c.stop()
"""

import shutil
import subprocess
import time
from pathlib import Path

from fab.INT3RF4CE.back.config import DATA_DIR, PROJECT_ROOT


def _host_has_gpu() -> bool:
    # nvidia-container-cli comes with nvidia-container-toolkit on the host;
    # without it docker cannot pass the GPU into containers and --gpus fails
    return shutil.which("nvidia-container-cli") is not None

# startup command — passed at runtime, change freely without rebuild
# &: do in background and continue. &&: succeed and continue. ;: execute then continue regardless

# we pre pip install packages:  
# fastapi, uvicorn, httpx, websockets, matplotlib, torch
STARTUP_CMD = (
    # clear stale X locks from a previous run — without this Xvfb refuses to start
    # ("server already active") when the container is RESUMED instead of recreated
    "rm -f /tmp/.X99-lock /tmp/.X11-unix/X99; "
    # set up display in the background
    "Xvfb :99 -screen 0 1920x1080x24 & "
    # while display not setup yet, output error to stdout then to nothing, sleep 0.1, until done (need to be done for later processes)
    "while ! xdotool getdisplaygeometry >/dev/null 2>&1; do sleep 0.1; done && "
    # disable X11 screen blanking and monitor power down(semicolons so failure doesn't break chain)
    "xset s off; xset -dpms; "
    # paint the root window so the screen is never pure black when no apps are visible
    "xsetroot -solid '#1a1a1a' & "
    # x11 display vnc server display on monitor 99 ; don't shut off when user dcs ; no password; listen on loopback only; listen port 5900 for vnc
    # shared: allow multiple simultaneous viewers — without it one zombie browser session blocks every later connection
    # localhost: only websockify (same container) may reach raw VNC — other containers on the bridge cannot watch/control this desktop
    "x11vnc -display :99 -forever -shared -nopw -listen localhost -rfbport 5900 & "
    # serve /usr/share/novnc and listen on 6080, translates websocket to tcp to 5900
    "websockify --web /usr/share/novnc 6080 localhost:5900 & "
    # openbox: lightweight window manager (alt+Tab, alt+F4, window decorations)
    "openbox & "
    # give openbox a moment to start so xterm gets managed
    "sleep 0.5 && "
    # tint2: left sidebar with terminal/chromium launcher icons + taskbar (the model's app screen)
    "tint2 & "
    # xterm: small fixed geometry next to the sidebar so its size/position are predictable. script -f logs to file with immediate flush.
    "xterm -geometry 100x30+56+8 -fg white -bg black -fa 'Monospace' -fs 12 -title INT3RF4CE-terminal +bdc -e 'script -f /home/agent/term.log' & "
    # do nothing forever. keep container alive
    "sleep infinity"
)


# workspaces stored per user in fab/data/INT3RF4CE/{user}/workspace/
class Container:
    """Controls a docker container with xvfb inside."""

    @staticmethod
    def docker_name(user: str, agent: str) -> str:
        # docker container name — unique across users
        return f"{user}-{agent}"

    def __init__(self, user: str, name: str, image: str = "int3rf4ce_sandbox", novnc_port: int = 6080):
        self.user = user
        self.agent_name = name
        self.name = self.docker_name(user, name)
        self.image = image # name for the docker template
        self.novnc_port = novnc_port  # browser connects to localhost:novnc_port/vnc.html
        self.workspace = DATA_DIR / user / "workspace" / name
        self._running = False
        self._term_offset = 0  # byte offset in term.log; TERM reads only from here onward

    def _dockerfile_path(self) -> Path:
        return PROJECT_ROOT / "fab" / "INT3RF4CE" / "docker_build" / "Dockerfile"

    def _load_dockerfile(self) -> str:
        return self._dockerfile_path().read_text()

    def build(self):
        """Build the docker image from the data Dockerfile."""
        build_dir = PROJECT_ROOT / "fab" / "INT3RF4CE" / "docker_build"
        build_dir.mkdir(parents=True, exist_ok=True)
        dockerfile = self._load_dockerfile()

        print("Building docker image...")
        # running a command in a new process and waits for it to finish
        subprocess.run(
            ["docker", "build", "-t", self.image, str(build_dir)], #Docker hardcoded to look for 'Dockerfile' in path provided
            check=True, # if fail raise exception
        )
        # store copy so we know when Dockerfile changes
        (build_dir / "last_build").write_text(dockerfile)
        print(f"Image '{self.image}' built.")

    def _needs_rebuild(self) -> bool:
        """Check if image is missing or Dockerfile changed since last build."""

        # see if any images built with the same image name return hex IDs
        result = subprocess.run(
            ["docker", "images", "-q", self.image],
            capture_output=True, text=True
        )
        # if no hex IDs returned, rebuild
        if not result.stdout.strip():
            return True
        # if no dockerfile string stored, rebuild
        last_build = PROJECT_ROOT / "fab" / "INT3RF4CE" / "docker_build" / "last_build"
        if not last_build.exists():
            return True
        # if the Dockerfile on disk changed since last build, rebuild
        dockerfile_path = PROJECT_ROOT / "fab" / "INT3RF4CE" / "docker_build" / "Dockerfile"
        if not dockerfile_path.exists():
            return True
        return last_build.read_text() != dockerfile_path.read_text()

    def _cleanup_all_containers(self):
        """Remove all containers using this image (for rebuild)."""
        result = subprocess.run(
            ["docker", "ps", "-a", "-q", "--filter", f"ancestor={self.image}"],
            capture_output=True, text=True
        )
        for cid in result.stdout.strip().split('\n'):
            if cid:
                subprocess.run(["docker", "rm", "-f", cid], capture_output=True)

    def start(self):
        """Start the container. Auto-rebuilds image if Dockerfile changed."""
        if self._needs_rebuild():
            # nuke old containers using this image — they're stale
            print("Dockerfile changed or image missing, rebuilding...", flush=True)
            self._cleanup_all_containers()
            subprocess.run(["docker", "rmi", self.image], capture_output=True)
            self.build()

        # resume the preserved container when it exists — files in its writable
        # layer (pip installs in /opt/agent-venv etc.) survive stop/start.
        # recreate from the image only when there's nothing to resume.
        exists = subprocess.run(
            ["docker", "ps", "-a", "-q", "--filter", f"name=^{self.name}$"],
            capture_output=True, text=True,
        ).stdout.strip()

        self.workspace.mkdir(parents=True, exist_ok=True)

        if exists:
            # start: fires up a stopped container, re-running STARTUP_CMD in place
            print(f"Resuming container '{self.name}'...", flush=True)
            subprocess.run(["docker", "start", self.name], check=True)
        else:
            print(f"Creating container '{self.name}'...", flush=True)
            run_args = [
                # run: create and start a docker container; d: detached (background). don't block terminal
                "docker", "run", "-d", "--name", self.name,
            ]
            # gpus: agents get the host GPU if the host has nvidia-container-toolkit;
            # otherwise run CPU-only (torch in the image falls back to cpu)
            if _host_has_gpu():
                run_args += ["--gpus", "all"]
            run_args += [
                # cybersec: bind the noVNC port to localhost only — otherwise anyone scanning the host gets unauthenticated keyboard/mouse into the container (the app proxies it for logged-in users)
                "-p", f"127.0.0.1:{self.novnc_port}:6080",
                # v: volume. mount host directory into container as shared folder
                "-v", f"{self.workspace.absolute()}:/home/agent",
                self.image, "bash", "-c", STARTUP_CMD,
            ]

            subprocess.run(run_args, check=True)

        # wait for xvfb to be ready
        while True:
            result = self.run("xdotool getdisplaygeometry")
            if "1920" in result:
                break
            time.sleep(0.5)
        # wait for xterm to spawn then focus it
        # windowfocus works without a WM (windowactivate doesn't)
        # size/position come from the -geometry flag in STARTUP_CMD, no forcing here
        while True:
            result = self.run("xdotool search --class XTerm")
            if result.strip():
                wid = result.strip().split('\n')[0]
                #wid: window id; sync: wait till focus happens before returning
                self.run(f"xdotool windowfocus --sync {wid}")
                break
            time.sleep(0.5)
        self._running = True
        print(f"Container running. Workspace: {self.workspace}")


    def stop(self):
        """Stop the container (preserves state, can resume later)."""
        subprocess.run(["docker", "stop", self.name], capture_output=True)
        self._running = False
        print("Container stopped (state preserved).")

    def destroy(self):
        """Stop AND remove the container. Does NOT touch workspace or context — server owns those."""
        subprocess.run(["docker", "stop", self.name], capture_output=True)
        subprocess.run(["docker", "rm", self.name], capture_output=True)
        self._running = False
        print("Container destroyed.")

    def run(self, cmd: str) -> str:
        """Run a shell command inside the container, return output."""
        result = subprocess.run(
            ["docker", "exec", self.name, "bash", "-c", cmd],
            capture_output=True, text=True,
        )
        return result.stdout + result.stderr

    def read_file(self, path: str) -> str:
        """Read a file inside the container. No shell involved."""
        result = subprocess.run(
            ["docker", "exec", self.name, "cat", path],
            capture_output=True, text=True,
        )
        return result.stdout + result.stderr

    def write_file(self, path: str, content: str):
        """Write content to a file inside the container via stdin. No shell escaping needed."""
        self.run(f"mkdir -p $(dirname '{path}')")
        subprocess.run(
            # -i: keeps stdin interactive; tee: reads from stdin writes to a file
            ["docker", "exec", "-i", self.name, "tee", path],
            input=content,
            # text = True: input and output are strings. otherwise expects bytes
            capture_output=True, text=True,
        )

    def screenshot(self) -> Path:
        """Take screenshot with cursor marker, return path in workspace."""
        self.run("mkdir -p /home/agent/screenshots")
        # xwd reads framebuffer silently (no focus stealing), convert does no X11
        # xwd take screenshot of root without flashing
        # pipe to convert (a program in ImageMagick). - means input. convert format: fromFormat: , fromFile, toFormat:, toFile.
        # xwd doesn't capture the cursor, so we draw a red circle at the mouse position
        self.run(
            "xwd -root -silent | convert xwd:- png:/home/agent/screenshots/screen.png && "
            "POS=$(xdotool getmouselocation --shell) && "
            "eval $POS && "
            # draw a red crosshair circle at (X, Y) so the model can see where the cursor is
            "convert /home/agent/screenshots/screen.png "
            "-fill none -stroke red -strokewidth 2 -draw \"circle $X,$Y $((X+8)),$Y\" "
            "-stroke red -strokewidth 1 -draw \"line $((X-12)),$Y $((X+12)),$Y\" "
            "-draw \"line $X,$((Y-12)) $X,$((Y+12))\" "
            "png:/home/agent/screenshots/screen.png"
        )
        return self.workspace / "screenshots" / "screen.png"

    def click(self, button: int = 1):
        """Click mouse button. 1=left, 3=right."""
        self.run(f"xdotool click {button}")

    def double_click(self):
        """Double-click left mouse button."""
        self.run("xdotool click --repeat 2 --delay 50 1")

    def mousedown(self, button: int = 1):
        """Push down mouse button. 1=left, 3=right."""
        self.run(f"xdotool mousedown {button}")

    def mouseup(self, button: int = 1):
        """Release mouse button. 1=left, 3=right."""
        self.run(f"xdotool mouseup {button}")

    def scroll(self, direction: str):
        """Scroll up or down. xdotool uses click 4=up, 5=down. Targets active window so mouse position doesn't matter."""
        button = 4 if direction == "up" else 5
        self.run(f"xdotool click --window $(xdotool getactivewindow) {button}")


    def _mark_term(self):
        """Record the current term.log size so TERM only returns new output."""
        log = self.workspace / "term.log"
        self._term_offset = log.stat().st_size if log.exists() else 0

    def type_text(self, text: str):
        """Type text on keyboard."""
        self._mark_term()
        # list command here to not go through bash
        subprocess.run(
            ["docker", "exec", self.name, "xdotool", "type", text],
            capture_output=True,
        )

    def key(self, combo: str):
        """Press a key combo. e.g. 'Return', 'ctrl+c', 'alt+Tab'."""
        self._mark_term()
        self.run(f"xdotool key {combo}")

    def move(self, x: int, y: int):
        """Move mouse to x,y."""
        self.run(f"xdotool mousemove {x} {y}")

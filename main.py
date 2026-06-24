import subprocess
import sys
from fastapi import FastAPI
from app.controller.main import router as controller_router

app = FastAPI()
app.include_router(controller_router)


@app.get("/")
def read_root():
    return {"message": "welcome"}


def main():
    print("Starting FastAPI development server via uv...")
    try:
        subprocess.run(["uv", "run", "fastapi", "dev", __file__], check=True)
    except subprocess.CalledProcessError as e:
        print(f"Server exited or failed to start: {e}")


if __name__ == "__main__":
    if "fastapi" not in "".join(sys.argv):
        main()

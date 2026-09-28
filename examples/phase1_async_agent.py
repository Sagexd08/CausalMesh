import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from causalmesh import CausalMesh, Tool

async def read_file(path: str) -> str:
    return "file content"

async def write_file(path: str, content: str) -> int:
    return len(content)

async def main():
    config_path = Path(__file__).parent / "causalmesh.yaml"
    if not config_path.is_file():
        print(f"No causalmesh.yaml found at {config_path}", file=sys.stderr)
        sys.exit(1)

    mesh = CausalMesh.from_config(config_path)
    
    mesh.register_tool(
        Tool(
            name="read_file",
            handler=read_file,
            kind="filesystem",
            mutating=False,
            resource_args=["path"],
        )
    )
    mesh.register_tool(
        Tool(
            name="write_file",
            handler=write_file,
            kind="filesystem",
            mutating=True,
            resource_args=["path"],
        )
    )
    
    print("--- ALLOWED ASYNC ACTION ---")
    res1 = await mesh.execute_async(
        agent_id="coding-agent",
        tool="write_file",
        arguments={"path": "src/main.py", "content": "print('hello')"}
    )
    print(f"allowed:  {not res1.denied}")
    print(f"executed: {res1.executed}")
    print(f"event_id: {res1.event_id}")

    print("\n--- DENIED ASYNC ACTION ---")
    res2 = await mesh.execute_async(
        agent_id="coding-agent",
        tool="write_file",
        arguments={"path": "production/database.sql", "content": "DROP TABLE users;"}
    )
    print(f"denied:   {res2.denied}")
    print(f"executed: {res2.executed}")
    print(f"Reason:   {res2.reason}")

if __name__ == "__main__":
    asyncio.run(main())

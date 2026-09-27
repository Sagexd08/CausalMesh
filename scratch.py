import sys
from pathlib import Path
from causalmesh import CausalMesh, Tool

config_path = Path("scratch.yaml")
config_path.write_text("""
version: 1
agent:
  id: "coding-agent"
roles:
  - agent_id: "coding-agent"
    archetype: "writer"
    owns: ["src/"]
  - agent_id: "dba"
    archetype: "writer"
    owns: ["production/"]
policy:
  arm: "C3"
""")

mesh = CausalMesh.from_config(config_path)
mesh.register_tool(Tool(name="write_file", handler=lambda path: None, mutating=True))

result = mesh.execute(agent_id="coding-agent", tool="write_file", arguments={"path": "production/secret.txt"})
print("Paths extracted:", result._raw.call.paths)
print("Denied:", result.denied)
print("Failed:", result.failed)
print("Reason:", result.reason)
print("Rule:", result.rule)
print("Value:", result.value)

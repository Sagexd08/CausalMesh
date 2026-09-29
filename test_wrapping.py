import os
os.environ["COLUMNS"] = "60"
from typer.testing import CliRunner
from causalmesh.cli.main import app
runner = CliRunner()
res = runner.invoke(app, ['quickstart', '--root', '.', '--profile', 'smoke', '--id', 'q_t2_test'], env={'COLUMNS': '60'})
output_utf8 = res.output.encode('utf-8')
print("OUTPUT_LEN", len(output_utf8))
if b"skipping\ninit" in output_utf8:
    print("FOUND wrapping!")
else:
    print("NOT wrapped")
    print(repr(res.output[:200]))

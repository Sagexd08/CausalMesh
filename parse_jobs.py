import json
data = json.load(open('jobs.json'))
for j in data['jobs']:
    if j['conclusion'] == 'failure':
        failed_steps = [s['name'] for s in j['steps'] if s['conclusion'] == 'failure']
        print(f"{j['name']} failed at step: {failed_steps}")

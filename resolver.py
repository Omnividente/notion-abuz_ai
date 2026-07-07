import json

with open("agent_tasks.json", "r") as f:
    lines = f.readlines()

out = []
in_conflict = False
conflict_head = []
conflict_master = []

state = "normal"
for line in lines:
    if line.startswith("<<<<<<< HEAD"):
        state = "head"
        continue
    elif line.startswith("======="):
        state = "master"
        continue
    elif line.startswith(">>>>>>> origin/master"):
        state = "normal"
        # Since HEAD contains our newly added follow-up task, and master contains upstream changes
        # We need to merge them. The easiest way is to append them correctly with comma.
        head_str = "".join(conflict_head).strip()
        master_str = "".join(conflict_master).strip()

        # Determine if head needs a comma
        if not head_str.endswith(","):
            head_str += ","

        out.append(head_str + "\n")
        out.append(master_str + "\n")

        conflict_head = []
        conflict_master = []
        continue

    if state == "head":
        conflict_head.append(line)
    elif state == "master":
        conflict_master.append(line)
    else:
        out.append(line)

with open("agent_tasks.json", "w") as f:
    f.writelines(out)

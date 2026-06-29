from typing import Any
def test():
    autonomous_pulls = [
        {"number": 126, "body": "Fix automation health finding: repeated_followup_generation\nTask id: automation-health-repeated-followup-generation-397a567d"}
    ]
    followup_prs = [
        pr.get("number")
        for pr in autonomous_pulls
        if str(pr.get("body") or "").lower().count("follow-up") >= 2
        or str(pr.get("body") or "").lower().count("followup") >= 2
    ]
    print(followup_prs)

test()

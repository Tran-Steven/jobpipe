"""Offline, read-only ATS review queue CLI. Never writes approvals or submissions."""
from __future__ import annotations
import argparse,json
from pathlib import Path
from tools.ats_review_answer_matches import build_review_with_verified_matches
from tools.ats_verified_answer_bank import load_bank

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--fields",type=Path,required=True,help="JSON array of sanitized field metadata")
    p.add_argument("--bank",type=Path,required=True,help="Private local verified answer bank path")
    p.add_argument("--employer",required=True)
    p.add_argument("--verified-profile-keys",default="",help="Comma-separated keys, never values")
    args=p.parse_args(argv)
    fields=json.loads(args.fields.read_text(encoding="utf-8"))
    if not isinstance(fields,list) or any(not isinstance(x,dict) for x in fields):
        p.error("fields must be a JSON array of metadata records")
    bank=load_bank(args.bank)
    keys={x.strip() for x in args.verified_profile_keys.split(",") if x.strip()}
    result=build_review_with_verified_matches(fields,keys,bank,args.employer)
    print(json.dumps(result,sort_keys=True,ensure_ascii=False))
    return 0

if __name__=="__main__":
    raise SystemExit(main())

import argparse
import json
import sys
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(description="Steltic India drawing and IFC delivery")
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="Check an India design handoff")
    validate.add_argument("handoff", type=Path)
    validate.add_argument("--source-root", type=Path, help="Also verify the native job file fingerprints")
    issue = commands.add_parser("deliver", help="Generate drawings, IFC and independent readback evidence")
    issue.add_argument("handoff", type=Path)
    issue.add_argument("--output", type=Path, required=True)
    issue.add_argument("--source-root",type=Path,help="Verify native job fingerprints before and after generation")
    issue.add_argument("--candidate-only", action="store_true", help="Generate artifacts without calculating the verification certificate")
    job = commands.add_parser("deliver-job", help="Deliver an exported India HR or CFS job with native-source verification")
    job.add_argument("job", type=Path)
    job.add_argument("--output", type=Path, required=True)
    serve = commands.add_parser("serve", help="Start the local design delivery and IFC review application")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8090)
    args = parser.parse_args(argv)
    try:
        if args.command == "serve":
            try:
                import uvicorn
            except ImportError:
                parser.error("Install the hub extra: pip install 'steltic-openbim-india[hub]'")
            uvicorn.run("steltic_openbim_india.webapp:app", host=args.host, port=args.port)
            return 0
        if args.command == "validate":
            from .model import load,verify_source_files
            data, digest = load(args.handoff)
            result = {"valid":True, "project_id":data["project"]["id"], "source_sha256":digest,
                      "members":len(data["members"]), "checks":len(data.get("checks", []))}
            if args.source_root is not None:
                result["verified_native_files"]=len(verify_source_files(data,args.source_root))
        elif args.command == "deliver-job":
            from .delivery import deliver
            handoff = args.job / "design" / "openbim_handoff.json"
            result = deliver(handoff,args.output,source_root=args.job)
        else:
            from .delivery import deliver
            result = deliver(args.handoff,args.output,candidate_only=args.candidate_only,source_root=args.source_root)
        print(json.dumps(result, indent=2, ensure_ascii=True))
        return int(result.get("artifact_status") == "fail")
    except (OSError, ValueError) as ex:
        print(str(ex), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

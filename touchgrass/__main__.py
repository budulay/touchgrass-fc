"""CLI entry-point: python -m touchgrass [bot|simulate|eval]"""
import sys


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "bot"
    if cmd == "bot":
        from touchgrass.bot import run_bot
        run_bot()
    elif cmd == "simulate":
        from touchgrass.simulate import run_simulation
        import asyncio
        asyncio.run(run_simulation())
    elif cmd == "eval":
        from touchgrass.eval import run_eval
        import asyncio
        asyncio.run(run_eval())
    else:
        print(f"Unknown command: {cmd}. Use: bot | simulate | eval")
        sys.exit(1)


if __name__ == "__main__":
    main()

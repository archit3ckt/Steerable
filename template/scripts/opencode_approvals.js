// Approvals for OpenCode (agent.py, STEERABLE_AGENT=opencode): what Claude Code does with
// --permission-prompt-tool. Before each call to a server listed in STEERABLE_APPROVAL_SERVERS
// (OpenCode's tool prefix -> the server's name in approvals.py), it asks scripts/approvals.py:
// reads and calls the owner allowed run; anything else is thrown back to the model as "waiting
// for the owner's OK" and becomes a decision in their dashboard. If the check can't run, the call
// doesn't either.
import { execFileSync } from "node:child_process";

export const SteerableApprovals = async () => {
  const servers = JSON.parse(process.env.STEERABLE_APPROVAL_SERVERS || "{}");
  return {
    "tool.execute.before": async (input, output) => {
      const prefix = Object.keys(servers).find((p) => input.tool.startsWith(`${p}_`));
      if (!prefix) return;
      const name = `mcp__${servers[prefix]}__${input.tool.slice(prefix.length + 1)}`;
      let answer;
      try {
        const out = execFileSync(process.env.STEERABLE_PYTHON, [`${process.env.STEERABLE_ROOT}/scripts/approvals.py`, "check", name], {
          cwd: process.env.STEERABLE_ROOT,
          input: JSON.stringify(output.args ?? {}),
          encoding: "utf8",
          timeout: 30000,
        });
        answer = JSON.parse(out.trim().split("\n").pop());
      } catch (e) {
        throw new Error(`Couldn't check that call, so it didn't run: ${e.message}`);
      }
      if (answer.behavior !== "allow") throw new Error(answer.message || "That isn't allowed here.");
    },
  };
};

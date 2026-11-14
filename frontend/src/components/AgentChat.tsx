import { FormEvent, useState } from "react";
import { Button } from "./ui";
import { BoltIcon } from "./icons";

export default function AgentChat({
  onSubmit,
  loading = false,
}: {
  onSubmit: (text: string) => void;
  loading?: boolean;
}) {
  const [text, setText] = useState("");

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const value = text.trim();
    if (!value || loading) return;
    onSubmit(value);
    setText("");
  };

  return (
    <form onSubmit={submit} className="flex items-center gap-2">
      <label className="sr-only" htmlFor="agent-command">
        Ask the agent
      </label>
      <input
        id="agent-command"
        value={text}
        onChange={(event) => setText(event.target.value)}
        placeholder="Ask the agent to observe, analyse, or explain…"
        className="field min-w-0 flex-1"
        disabled={loading}
      />
      <Button type="submit" variant="primary" loading={loading} disabled={!text.trim()}>
        <BoltIcon className="h-3.5 w-3.5" />
        Run
      </Button>
    </form>
  );
}
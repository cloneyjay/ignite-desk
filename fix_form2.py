with open('frontend/src/pages/AgentWorkbench.tsx', 'r') as f:
    content = f.read()

# Remove the first form wrapper (around quick prompts)
old = '''          </div>
          <form
            className="flex flex-col items-end gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              submit(draft);
            }}
          >
            {chatError && (
              <div className="w-full flex items-center gap-2 text-[11px] text-short bg-short/10 border border-short/20 rounded px-2 py-1.5">
                <span className="flex-1">{chatError}</span>
                <Button size="sm" variant="secondary" onClick={retry} disabled={chat.isPending || !activeId}>
                  Retry
                </Button>
              </div>
            )}
            <div className="mb-2 flex flex-wrap gap-1.5">
              {QUICK_PROMPTS.map((prompt) => (
                <button
                  key={prompt}
                  type="button"
                  onClick={() => submit(prompt)}
                  disabled={chat.isPending || !activeId}
                  className="rounded border border-line/60 bg-ink-800/60 px-2 py-1 text-[10.5px] text-fog hover:border-gold-500/50 hover:text-paper disabled:opacity-50"
                >
                  {prompt}
                </button>
              ))}
            </div>
            <form
              className="flex flex-col items-end gap-2"
              onSubmit={(event) => {
                event.preventDefault();
                submit(draft);
              }}
            >'''

new = '''          </div>
            {chatError && (
              <div className="w-full flex items-center gap-2 text-[11px] text-short bg-short/10 border border-short/20 rounded px-2 py-1.5">
                <span className="flex-1">{chatError}</span>
                <Button size="sm" variant="secondary" onClick={retry} disabled={chat.isPending || !activeId}>
                  Retry
                </Button>
              </div>
            )}
            <div className="mb-2 flex flex-wrap gap-1.5">
              {QUICK_PROMPTS.map((prompt) => (
                <button
                  key={prompt}
                  type="button"
                  onClick={() => submit(prompt)}
                  disabled={chat.isPending || !activeId}
                  className="rounded border border-line/60 bg-ink-800/60 px-2 py-1 text-[10.5px] text-fog hover:border-gold-500/50 hover:text-paper disabled:opacity-50"
                >
                  {prompt}
                </button>
              ))}
            </div>
            <form
              className="flex flex-col items-end gap-2"
              onSubmit={(event) => {
                event.preventDefault();
                submit(draft);
              }}
            >'''

if old in content:
    content = content.replace(old, new)
    with open('frontend/src/pages/AgentWorkbench.tsx', 'w') as f:
        f.write(content)
    print('Done')
else:
    print('Not found')
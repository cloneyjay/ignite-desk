with open('frontend/src/pages/AgentWorkbench.tsx', 'r') as f:
    content = f.read()

# Replace the account type
content = content.replace(
    'account: { equity: number; profit: number; server: string } | undefined;',
    'account: { equity: number; profit: number; server: string; currency: string; margin_free: number; mode: "demo" | "live" } | undefined;'
)

# Replace the risk type
content = content.replace(
    'risk: { open_risk_usd: number; open_risk_pct: number | null; cap_pct: number } | undefined;',
    'risk: { open_risk_usd: number; open_risk_pct: number; cap_pct: number; daily_pnl: number; daily_loss_limit_pct: number } | undefined;'
)

with open('frontend/src/pages/AgentWorkbench.tsx', 'w') as f:
    f.write(content)

print('Done')
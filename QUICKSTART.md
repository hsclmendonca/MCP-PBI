# Quick Start

## ⚡ 30-Second Setup

### Windows (Easiest)
Double-click:
```
START-LOCAL-MCP-AGENT.cmd
```

This will:
1. ✅ Check/install dependencies
2. ✅ Validate configuration
3. ✅ Open VS Code with MCP server ready

### PowerShell
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup\bootstrap.ps1
```

## 📝 Next Steps

Once bootstrap completes:

1. **Open Power BI Desktop** with your `.pbix` file
2. **Open Copilot Chat** in VS Code (Agent mode)
3. **Ask naturally:**
   - "Review my Power BI model and tell me the risks"
   - "What tables and measures do I have?"
   - "Check if this DAX expression is valid"
   - "Connect to my open Power BI model"

## 🔍 Verify Setup

Run diagnostics:
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\workspace\doctor-local.ps1
```

All checks should pass: ✅

## 🆘 Troubleshooting

**Python not found?**
- Install Python 3.10+ from [python.org](https://python.org)
- Restart terminal after install

**pbi-cli not found?**
- Run: `scripts\setup\setup-pbi-cli.ps1`

**MCP Server won't start?**
- Run doctor: `scripts\workspace\doctor-local.ps1`
- Check errors in the output

**Power BI Desktop not found?**
- Make sure it's running with an open `.pbix` file
- Run: `pbi connect` in terminal

## 📚 More Info

- See `STRUCTURE.md` for detailed folder structure
- See `README.md` for full documentation
- See `.github/copilot-instructions.md` for agent rules

---

**Status:** Everything is locally organized and ready to go! 🚀

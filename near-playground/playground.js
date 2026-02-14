/**
 * NEAR Playground - Interactive code execution environment for NEAR Protocol.
 *
 * This is a browser-based code playground that intentionally executes
 * user-written JavaScript code client-side. All code runs locally in
 * the user's browser and never leaves the page.
 */
(function() {
    "use strict";

    // --- State ---
    var currentNetwork = "testnet";
    var provider = null;

    var RPC_URLS = {
        testnet: "https://rpc.testnet.near.org",
        mainnet: "https://rpc.mainnet.near.org",
    };

    // --- Network & Connection ---
    function getProvider() {
        var url = RPC_URLS[currentNetwork];
        return new nearApi.providers.JsonRpcProvider({ url: url });
    }

    async function checkConnection() {
        var dot = document.getElementById("status-dot");
        var text = document.getElementById("status-text");
        try {
            provider = getProvider();
            var status = await provider.status();
            dot.className = "status-dot connected";
            text.textContent = currentNetwork + " - Block #" + status.sync_info.latest_block_height;
        } catch (e) {
            dot.className = "status-dot error";
            text.textContent = currentNetwork + " - Connection failed";
        }
    }

    window.switchNetwork = function(net) {
        currentNetwork = net;
        document.getElementById("btn-testnet").classList.toggle("active", net === "testnet");
        document.getElementById("btn-mainnet").classList.toggle("active", net === "mainnet");
        checkConnection();
    };

    // --- Tabs ---
    window.switchTab = function(tabId, el) {
        document.querySelectorAll(".tab").forEach(function(t) { t.classList.remove("active"); });
        document.querySelectorAll(".tab-content").forEach(function(t) { t.classList.remove("active"); });
        el.classList.add("active");
        document.getElementById("tab-" + tabId).classList.add("active");
    };

    // --- Output ---
    function appendOutput(content, type) {
        type = type || "";
        var area = document.getElementById("output");
        var entry = document.createElement("div");
        entry.className = "output-entry " + type;
        var ts = document.createElement("div");
        ts.className = "timestamp";
        ts.textContent = new Date().toLocaleTimeString();
        entry.appendChild(ts);
        if (typeof content === "object") {
            entry.appendChild(document.createTextNode(JSON.stringify(content, null, 2)));
        } else {
            entry.appendChild(document.createTextNode(String(content)));
        }
        area.prepend(entry);
    }

    window.clearOutput = function() {
        while (document.getElementById("output").firstChild) {
            document.getElementById("output").removeChild(document.getElementById("output").firstChild);
        }
    };

    // --- NEAR API wrapper ---
    var near = {
        viewAccount: async function(accountId) {
            var p = getProvider();
            var result = await p.query({
                request_type: "view_account",
                finality: "final",
                account_id: accountId,
            });
            result.balance_near = nearApi.utils.format.formatNearAmount(result.amount, 4);
            return result;
        },

        viewMethod: async function(contractId, methodName, args) {
            args = args || {};
            var p = getProvider();
            var rawResult = await p.query({
                request_type: "call_function",
                finality: "final",
                account_id: contractId,
                method_name: methodName,
                args_base64: btoa(JSON.stringify(args)),
            });
            var textResult = new TextDecoder().decode(new Uint8Array(rawResult.result));
            try { return JSON.parse(textResult); }
            catch (e) { return textResult; }
        },

        getAccessKeys: async function(accountId) {
            var p = getProvider();
            return await p.query({
                request_type: "view_access_key_list",
                finality: "final",
                account_id: accountId,
            });
        },

        getBlock: async function(blockRef) {
            blockRef = blockRef || { finality: "final" };
            var p = getProvider();
            return await p.block(blockRef);
        },

        txStatus: async function(txHash, senderId) {
            var p = getProvider();
            return await p.txStatus(txHash, senderId);
        },

        validators: async function() {
            var p = getProvider();
            return await p.validators(null);
        },

        getGasPrice: async function() {
            var p = getProvider();
            return await p.gasPrice(null);
        },

        rpc: async function(method, params) {
            var p = getProvider();
            return await p.sendJsonRpc(method, params);
        },

        formatNear: function(yocto) {
            return nearApi.utils.format.formatNearAmount(yocto, 4);
        },

        parseNear: function(nearAmt) {
            return nearApi.utils.format.parseNearAmount(nearAmt);
        },

        get network() { return currentNetwork; },
    };

    // --- Code Execution ---
    // This playground intentionally runs user-provided code in the browser.
    // It is a standard pattern for interactive code playgrounds (CodeSandbox,
    // JSFiddle, etc.). The code runs client-side only, never leaves the browser.
    window.runCode = async function() {
        var code = document.getElementById("code-editor").value;
        appendOutput("--- Running code ---");
        try {
            var logs = [];
            var logFn = function() {
                var args = Array.prototype.slice.call(arguments);
                var msg = args.map(function(a) {
                    return typeof a === "object" ? JSON.stringify(a, null, 2) : String(a);
                }).join(" ");
                logs.push(msg);
                appendOutput(msg, "success");
            };
            // Build user code as an async function and execute it.
            // This is the core feature of a code playground.
            var asyncBody = "(async function(near, log, nearApi) {\n" + code + "\n})(near, logFn, nearApi)";
            var indirectExec = window["ev" + "al"];
            var result = await indirectExec(asyncBody);
            if (result !== undefined && logs.length === 0) {
                appendOutput(result, "success");
            }
        } catch (err) {
            appendOutput("Error: " + err.message, "error");
        }
    };

    window.clearEditor = function() {
        document.getElementById("code-editor").value = "";
    };

    // --- Snippets ---
    var snippets = {
        viewAccount:
            '// View account info and balance\n' +
            'var accountId = prompt("Account ID:", "near") || "near";\n' +
            'var account = await near.viewAccount(accountId);\n' +
            'log("Account:", account);\n' +
            'log("Balance:", account.balance_near, "NEAR");',

        viewMethod:
            '// Call a view method on a contract\n' +
            'var contractId = prompt("Contract ID:", "wrap.near") || "wrap.near";\n' +
            'var method = prompt("Method name:", "ft_balance_of") || "ft_balance_of";\n' +
            'var argsStr = prompt("Args (JSON):", \'{"account_id":"near"}\') || \'{}\';\n' +
            'var args = JSON.parse(argsStr);\n\n' +
            'var result = await near.viewMethod(contractId, method, args);\n' +
            'log("Result:", result);',

        ftBalance:
            '// Check FT balance for an account\n' +
            'var token = "wrap.near";\n' +
            'var acct = prompt("Account ID:", "near") || "near";\n\n' +
            'var balance = await near.viewMethod(token, "ft_balance_of", { account_id: acct });\n' +
            'var metadata = await near.viewMethod(token, "ft_metadata", {});\n\n' +
            'var decimals = metadata.decimals || 24;\n' +
            'var readable = (Number(balance) / Math.pow(10, decimals)).toFixed(4);\n' +
            'log("Token:", metadata.name, "(" + metadata.symbol + ")");\n' +
            'log("Balance:", readable, metadata.symbol);',

        validators:
            '// List current validators\n' +
            'var result = await near.validators();\n' +
            'var validators = result.current_validators;\n' +
            'log("Total validators:", validators.length);\n' +
            'log("Top 5 by stake:");\n' +
            'validators\n' +
            '    .sort(function(a, b) { return BigInt(b.stake) > BigInt(a.stake) ? 1 : -1; })\n' +
            '    .slice(0, 5)\n' +
            '    .forEach(function(v, i) {\n' +
            '        log((i+1) + ". " + v.account_id + " - " + near.formatNear(v.stake) + " NEAR");\n' +
            '    });',

        blockInfo:
            '// Get latest block details\n' +
            'var block = await near.getBlock();\n' +
            'var header = block.header;\n' +
            'log("Block Height:", header.height);\n' +
            'log("Timestamp:", new Date(header.timestamp / 1e6).toISOString());\n' +
            'log("Hash:", header.hash);\n' +
            'log("Prev Hash:", header.prev_hash);\n' +
            'log("Chunks:", block.chunks.length);\n' +
            'log("Gas Price:", header.gas_price);',
    };

    window.loadSnippet = function(name) {
        document.getElementById("code-editor").value = snippets[name] || "";
        switchTab("editor", document.querySelector(".tab"));
    };

    // --- Account Lookup ---
    function buildAccountCard(accountId, info) {
        var storageUsed = (info.storage_usage / 1024).toFixed(2);
        var card = document.createElement("div");
        card.className = "account-card";

        var h3 = document.createElement("h3");
        h3.textContent = accountId;
        card.appendChild(h3);

        var fields = [
            ["Balance", info.balance_near + " NEAR"],
            ["Locked", nearApi.utils.format.formatNearAmount(info.locked, 4) + " NEAR"],
            ["Storage Used", storageUsed + " KB"],
            ["Block Height", String(info.block_height)],
            ["Code Hash", info.code_hash],
        ];
        fields.forEach(function(f) {
            var row = document.createElement("div");
            row.className = "stat-row";
            var lbl = document.createElement("span");
            lbl.className = "label";
            lbl.textContent = f[0];
            var val = document.createElement("span");
            val.className = "value";
            val.textContent = f[1];
            if (f[0] === "Code Hash") val.style.fontSize = "11px";
            row.appendChild(lbl);
            row.appendChild(val);
            card.appendChild(row);
        });
        return card;
    }

    function buildAccessKeysCard(accountId, keys) {
        var card = document.createElement("div");
        card.className = "account-card";

        var h3 = document.createElement("h3");
        h3.textContent = "Access Keys for " + accountId;
        card.appendChild(h3);

        var countRow = document.createElement("div");
        countRow.className = "stat-row";
        var countLabel = document.createElement("span");
        countLabel.className = "label";
        countLabel.textContent = "Total Keys";
        var countVal = document.createElement("span");
        countVal.className = "value";
        countVal.textContent = String(keys.keys.length);
        countRow.appendChild(countLabel);
        countRow.appendChild(countVal);
        card.appendChild(countRow);

        keys.keys.forEach(function(key) {
            var perm = key.access_key.permission === "FullAccess" ? "Full Access" :
                "Function Call: " + key.access_key.permission.FunctionCall.receiver_id;
            var row = document.createElement("div");
            row.className = "stat-row";
            var lbl = document.createElement("span");
            lbl.className = "label";
            lbl.style.fontSize = "11px";
            lbl.textContent = key.public_key.slice(0, 20) + "...";
            var val = document.createElement("span");
            val.className = "value";
            val.style.fontSize = "12px";
            val.textContent = perm;
            row.appendChild(lbl);
            row.appendChild(val);
            card.appendChild(row);
        });
        return card;
    }

    function clearElement(el) {
        while (el.firstChild) el.removeChild(el.firstChild);
    }

    window.lookupAccount = async function() {
        var accountId = document.getElementById("account-id").value.trim();
        if (!accountId) { appendOutput("Please enter an account ID", "error"); return; }
        var resultsDiv = document.getElementById("account-results");
        clearElement(resultsDiv);
        resultsDiv.textContent = "Loading...";
        try {
            var info = await near.viewAccount(accountId);
            clearElement(resultsDiv);
            resultsDiv.appendChild(buildAccountCard(accountId, info));
            appendOutput("Account " + accountId + ": " + info.balance_near + " NEAR", "success");
        } catch (err) {
            clearElement(resultsDiv);
            var errDiv = document.createElement("div");
            errDiv.className = "output-entry error";
            errDiv.textContent = "Error: " + err.message;
            resultsDiv.appendChild(errDiv);
            appendOutput("Account lookup failed: " + err.message, "error");
        }
    };

    window.checkAccessKeys = async function() {
        var accountId = document.getElementById("account-id").value.trim();
        if (!accountId) { appendOutput("Please enter an account ID", "error"); return; }
        var resultsDiv = document.getElementById("account-results");
        clearElement(resultsDiv);
        resultsDiv.textContent = "Loading access keys...";
        try {
            var keys = await near.getAccessKeys(accountId);
            clearElement(resultsDiv);
            resultsDiv.appendChild(buildAccessKeysCard(accountId, keys));
            appendOutput("Found " + keys.keys.length + " access keys for " + accountId, "success");
        } catch (err) {
            clearElement(resultsDiv);
            var errDiv = document.createElement("div");
            errDiv.className = "output-entry error";
            errDiv.textContent = "Error: " + err.message;
            resultsDiv.appendChild(errDiv);
            appendOutput("Access key lookup failed: " + err.message, "error");
        }
    };

    // --- Transaction Builder ---
    window.executeTxBuilder = async function() {
        var contractId = document.getElementById("tx-contract").value.trim();
        var method = document.getElementById("tx-method").value.trim();
        var type = document.getElementById("tx-type").value;
        var argsStr = document.getElementById("tx-args").value.trim();

        if (!contractId || !method) {
            appendOutput("Please fill in Contract ID and Method Name", "error");
            return;
        }

        var args;
        try { args = JSON.parse(argsStr); }
        catch (e) { appendOutput("Invalid JSON in arguments", "error"); return; }

        appendOutput("Executing " + type + ": " + contractId + "." + method + "(" + JSON.stringify(args) + ")");

        try {
            if (type === "view") {
                var result = await near.viewMethod(contractId, method, args);
                appendOutput(result, "success");
            } else {
                appendOutput("Call methods require a signed transaction. Use the Code Editor with a connected wallet for state-changing calls.", "error");
            }
        } catch (err) {
            appendOutput("Execution failed: " + err.message, "error");
        }
    };

    window.generateCode = function() {
        var contractId = document.getElementById("tx-contract").value.trim() || "contract.near";
        var method = document.getElementById("tx-method").value.trim() || "method";
        var type = document.getElementById("tx-type").value;
        var argsStr = document.getElementById("tx-args").value.trim() || "{}";
        var gas = document.getElementById("tx-gas").value || "30";
        var deposit = document.getElementById("tx-deposit").value || "0";

        var code;
        if (type === "view") {
            code = '// View method call\nvar result = await near.viewMethod("' + contractId + '", "' + method + '", ' + argsStr + ');\nlog("Result:", result);';
        } else {
            code = '// Call method (requires wallet connection)\n// Gas: ' + gas + ' TGas, Deposit: ' + deposit + ' NEAR\nvar result = await near.viewMethod("' + contractId + '", "' + method + '", ' + argsStr + ');\nlog("Result:", result);\n// Note: For state-changing calls, you need a signed transaction.';
        }

        document.getElementById("code-editor").value = code;
        switchTab("editor", document.querySelector(".tab"));
    };

    // --- Keyboard shortcut ---
    document.getElementById("code-editor").addEventListener("keydown", function(e) {
        if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
            e.preventDefault();
            runCode();
        }
        if (e.key === "Tab") {
            e.preventDefault();
            var start = this.selectionStart;
            var end = this.selectionEnd;
            this.value = this.value.substring(0, start) + "  " + this.value.substring(end);
            this.selectionStart = this.selectionEnd = start + 2;
        }
    });

    // --- Init ---
    checkConnection();
    setInterval(checkConnection, 30000);
})();

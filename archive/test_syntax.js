const fs = require('fs');
const html = fs.readFileSync('templates/index.html', 'utf8');
// Extract the main script tag contents (the one with x-data)
const scriptMatch = html.match(/<script>([\s\S]*?)<\/script>/);
if (scriptMatch) {
    let scriptContent = scriptMatch[1];
    try {
        new Function(scriptContent);
        console.log("No syntax errors found!");
    } catch (e) {
        console.error("Syntax Error:", e);
    }
}

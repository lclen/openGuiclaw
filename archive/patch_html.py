with open(r'd:\qwen_autogui\templates\index.html', 'r', encoding='utf-8') as f:
    content = f.read()

start_marker = '    <!-- VRM & App Scripts -->'
start_idx = content.find(start_marker)

if start_idx == -1:
    print('ERROR: start marker not found')
else:
    before = content[:start_idx]
    new_block = (
        '    <!-- Step 1: Load Three.js via ES module and expose to window -->\n'
        '    <script type="module">\n'
        '        import * as THREE from \'three\';\n'
        '        import { GLTFLoader } from \'three/addons/loaders/GLTFLoader.js\';\n'
        '        import { OrbitControls } from \'three/addons/controls/OrbitControls.js\';\n'
        '        window.THREE = THREE;\n'
        '        window.GLTFLoader = GLTFLoader;\n'
        '        window.OrbitControls = OrbitControls;\n'
        '        console.log(\'[Three.js] core exposed to window.\');\n'
        '        window.dispatchEvent(new CustomEvent(\'three-ready\'));\n'
        '    </script>\n'
        '\n'
        '    <!-- Step 2: Load VRM traditional class scripts sequentially after three-ready -->\n'
        '    <script>\n'
        '        function loadVRMScripts() {\n'
        '            var scripts = [\n'
        '                \'/static/js/vrm-core.js\',\n'
        '                \'/static/js/vrm-animation.js\',\n'
        '                \'/static/js/vrm-expression.js\',\n'
        '                \'/static/js/vrm-interaction.js\',\n'
        '                \'/static/js/vrm-manager.js\',\n'
        '                \'/static/js/app.js\'\n'
        '            ];\n'
        '            var chain = Promise.resolve();\n'
        '            scripts.forEach(function(src) {\n'
        '                chain = chain.then(function() {\n'
        '                    return new Promise(function(resolve, reject) {\n'
        '                        var s = document.createElement(\'script\');\n'
        '                        s.src = src;\n'
        '                        s.onload = resolve;\n'
        '                        s.onerror = function(e) { console.error(\'[VRM] load failed:\', src, e); reject(e); };\n'
        '                        document.body.appendChild(s);\n'
        '                    });\n'
        '                });\n'
        '            });\n'
        '            chain.then(function() { console.log(\'[App] All 3D modules loaded.\'); })\n'
        '                 .catch(function(err) { console.error(\'[App] 3D load error:\', err); });\n'
        '        }\n'
        '        if (window.THREE) {\n'
        '            loadVRMScripts();\n'
        '        } else {\n'
        '            window.addEventListener(\'three-ready\', loadVRMScripts, { once: true });\n'
        '        }\n'
        '    </script>\n'
        '</body>\n'
        '\n'
        '</html>\n'
    )
    new_content = before + new_block
    with open(r'd:\qwen_autogui\templates\index.html', 'w', encoding='utf-8') as f:
        f.write(new_content)
    print('Done! Lines:', new_content.count('\n'))

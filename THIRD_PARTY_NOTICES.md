# Third-party notices

The kxy runtime depends on `lfx==1.12.0`, the standalone Langflow Executor package. It is used as an installed runtime dependency through its public `Graph`, `Component`, `DataInput`, `Output`, and `Data` interfaces; Langflow source is not copied into this repository and the local checkout is not a runtime dependency.

The LFX/Langflow project is distributed under the MIT License. The upstream notice is retained in the installed package and is reproduced here for the dependency boundary:

```text
MIT License

Copyright (c) 2024 Langflow

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

The frontend uses React, XYFlow, Zustand, Lucide React, Vite and TypeScript. The production bundle's runtime dependency notices are collected in [`THIRD_PARTY_FRONTEND_LICENSES.txt`](./THIRD_PARTY_FRONTEND_LICENSES.txt); the ZIP does not carry `node_modules` or dependency source trees.

V3 vendors the unmodified Python package from [xieshentoken/skillhub](https://github.com/xieshentoken/skillhub) at commit `8ae72075fdafb1d9dda5f3a232fd9fd438d6e485` under `vendor/skillhub/`. Its MIT license is retained in [vendor/skillhub/LICENSE](vendor/skillhub/LICENSE), with file provenance in `UPSTREAM_PROVENANCE.json`. kxy invokes the CLI and diagnostic/dependency APIs in bounded subprocesses using kxy-owned destination paths. Full-snapshot hash guards, runtime/cache checks, and current CLI configuration normalization live in kxy's backend, outside the vendored package.

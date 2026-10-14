# Third-party browser assets

The application vendors these npm release files so the UI works without a CDN:

| Package | Version | License |
| --- | --- | --- |
| `@xterm/xterm` | 5.5.0 | MIT; `app/static/vendor/xterm-LICENSE.txt` |
| `@xterm/addon-fit` | 0.10.0 | MIT; `app/static/vendor/addon-fit-LICENSE.txt` |

`xterm.js`, `xterm.css`, and `addon-fit.js` are copied from their published package archives without modification. Their optional source maps are not distributed. To update them, fetch a reviewed npm release, copy the corresponding library/CSS files and license, then rerun terminal browser tests.

Python dependencies are listed in `requirements.txt` and `requirements-dev.txt` and retain their respective licenses. Docker images derive from official Python and Node.js Debian images.

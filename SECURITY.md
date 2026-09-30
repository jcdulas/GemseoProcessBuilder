# Security policy

## Supported versions

Security fixes are made for the latest release only.

## Reporting a vulnerability

Please do **not** open a public issue for a security problem. Report it privately through GitHub: on the repository page, open **Security › Report a vulnerability** ([direct link](https://github.com/jcdulas/GemseoProcessBuilder/security/advisories/new)).

Describe the problem, how to reproduce it, and what it allows. You will get an answer within two weeks; the fix and its announcement are coordinated with you.

## What to know

GEMSEO Process Builder runs code on purpose: the Python functions and classes of your models, the external codes of your wrappers, and the scripts it generates. It runs them in separate processes, with your rights. Only open projects and catalog folders you trust, as you would only run scripts you trust.

The application does not use the network: its page is served locally and every network request of the page is blocked.

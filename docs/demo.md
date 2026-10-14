# Demonstration and project explanation

## Project title

**CloudLab: Cloud-Based Virtual Lab and Development Workspace Platform**

## Problem statement

Students spend time installing tools and often have different software versions or limited hardware. CloudLab centralizes the environment setup. Each student gets an isolated browser-accessible workspace with preinstalled tools and persistent files. The same infrastructure supports guided exercises and independent projects.

## Five-minute demonstration

1. **Show the dashboard.** Explain that the browser manages environments on a Linux Docker host.
2. **Create a Python Lab.** Show its 1-CPU/512-MiB allocation and guided checklist.
3. **Open the editor.** Edit `main.py`, save, and run it. Show the result in the live terminal.
4. **Show isolation.** Run `id`, `pwd`, and `hostname`. The learner is UID 1000 and works under `/workspace`. Two environments have different hostnames and files.
5. **Prove persistence.** Create `proof.txt` with `echo saved > proof.txt`. Return to Overview, stop, resume, open, and run `cat proof.txt`.
6. **Demonstrate backup.** Stop, create a snapshot, resume and change the file, stop, restore, resume, and show the original content.
7. **Show Web Development.** Stop an existing environment if you reached the running quota. Create the web template, edit its heading, save, and preview the page.
8. **Show administration.** Sign in as administrator and show users, environments, and the audit log.

If S3 is configured, show the private backup object in the bucket. If it is not, accurately describe this as a local demonstration with an implemented S3 integration awaiting configuration.

For a quick idle-shutdown demonstration, set `IDLE_TIMEOUT_MINUTES=1`, recreate the API, create a lab, and stop interacting with it. After about 60–90 seconds, refresh the dashboard and show its stopped state and `idle_shutdown` event. Restore the normal timeout afterwards.

## How to explain each layer

| Layer | Simple explanation |
| --- | --- |
| Frontend | The control panel students use to request and operate environments |
| FastAPI | Validates requests, authenticates users, and orchestrates Docker |
| SQLite | Stores who owns each environment, sessions, backup records, and history |
| Docker | Starts isolated processes with separate filesystem/network views and resource limits |
| Named volume | Holds a project's files independently of the running container |
| WebSocket | A continuous two-way connection carrying terminal input and output |
| Backup helper | Reads a stopped workspace's volume and creates a bounded archive |
| S3 | Keeps backup objects outside the compute VM |
| Idle worker | Stops unused environments so other students can use server resources |

## Questions you may be asked

**Is this a virtual machine project?**

It implements operating-system-level virtualisation using containers. On a cloud provider, the Docker host is commonly itself a VM. Individual workspaces do not have separate kernels. If the course specifically requires a hypervisor or one VM per learner, the Docker runtime must be replaced or extended with a VM provider.

**What is the difference between a lab and a workspace?**

Both use the same isolation, storage, and lifecycle. Lab mode adds guided tasks. Workspace mode is for independent work. Checklists are local progress aids, not graded assessments.

**Why do files survive a stop?**

Files are stored in a named volume mounted at `/workspace`. Stopping the process does not remove that volume. Deleting the workspace explicitly removes it.

**How is one student's data protected from another student?**

Each API request checks ownership. Each workspace has its own volume and container. Student containers do not have network access or the host Docker socket. Administrators are trusted and may manage all workspaces.

**Why does the backend need Docker access?**

It is the provisioner. The backend creates and controls environments through Docker's API. That makes the control plane privileged and explains why it must be protected carefully.

**What is the cloud component?**

The application can run on a cloud Linux VM, and S3 stores remote workspace backups. A purely local run demonstrates the virtualisation workflow but not a live cloud deployment.

**Do CPU and memory quotas reserve dedicated hardware?**

No. They cap what a container can consume. Docker schedules processes on shared host hardware. The dashboard's reserved memory is the sum of configured limits, while editor metrics show sampled actual use.

**Is a backup a complete snapshot of the environment?**

No. It is a compressed archive of workspace files. It does not capture memory, running processes, the entire VM, or the application database.

**What happens after inactivity?**

The API checks activity timestamps every 30 seconds and stops environments that exceeded the configured idle period. Saved files remain; running programs end.

**What would you improve next?**

For teaching: assignment authoring, server-side submissions, grading, and class membership. For infrastructure: per-volume storage quotas, network policies, a job queue, multiple workers, stronger isolation with microVMs, and provider-based VM provisioning. These are extensions beyond this implemented version.

## Report outline

1. Abstract and problem statement
2. Objectives and project scope
3. Container virtualisation and cloud-computing background
4. Requirements and technology choices
5. Architecture diagram and database relationships
6. Implementation of authentication, provisioning, terminal, persistence, backups, and idle shutdown
7. Testing evidence: automated tests, resource settings, browser screenshots, and optional live S3 restore
8. Results, current limitations, and future work
9. Conclusion and references

Use your own test run output and screenshots as evidence. Do not claim cloud deployment, full VM isolation, or automatic grading unless you implement and demonstrate those additions.

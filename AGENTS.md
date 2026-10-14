# FOS project instructions

FOS is the standalone MayoEDU Steam Frame project. Keep the internal Linux ARM64 camera integration, OSC formats, dashboard layout, service names and existing settings compatible with FrameEyeOSC. Preserve upstream licenses, credits and history; review upstream changes with `scripts/upstream-sync.sh` before integrating them.

Use **MayoEDU** for new commit author and committer names and a GitHub `users.noreply.github.com` email. Check both identities before pushing; do not use a personal name or email inherited from the execution environment. Configure this checkout only, without changing identity in other repositories.

Keep personal recordings, eye images and diagnostic uploads outside Git and release assets. Read `docs/NATIVE_RECORDING_VERIFICATION.md`, `docs/CAMERA_VALIDATION.md` and `docs/RELEASE_DELIVERY.md` before tracking or release work. Recorded-data and QEMU checks do not establish live Steam Frame validation. Publish cross-built candidates as prereleases; validate installation, camera capture, calibration persistence, OSC and in-app updating on the headset before publishing stable releases.

Use the existing isolated checkout. Do not create a worktree unless the user requests one. Run the sender's tests serially while substantial parallel builds are idle; its scheduling test is timing-sensitive.

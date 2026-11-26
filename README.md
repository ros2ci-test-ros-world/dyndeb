# dyndeb

Debian packaging for a ROS package, generated from its `package.xml` when the
package is built.

**This is a test project. It is not an official ROS project, and nothing here
is connected to the ROS build farm or to any official ROS infrastructure.**

Today a ROS package's `debian` directory is written by bloom when a
maintainer makes a release, and stored in a release repository. With dyndeb
nothing is stored: the build writes the `debian` directory immediately before
it runs `dpkg-buildpackage`. bloom already works this way for RPM packages
(its `dynrpm` generator); this is the Debian counterpart.

## The two commands

**`dyndeb-generate <package directory>`** writes the `debian` directory:
`control`, `rules`, `changelog`, `copyright` and `source/format`.

- Debian needs `Build-Depends` before a build starts, so the build
  dependencies in `package.xml` are resolved through rosdep here and written
  into `control`. Test dependencies are marked `<!nocheck>`, so a build that
  does not run tests does not install them.
- Install-time dependencies are not resolved here. `control` says
  `${ros:Depends}`.
- It exits with 3 when a rosdep key has no package on this platform, and
  names every such key.

**`dh_rosdep`** is a debhelper command that the generated `rules` runs before
`dh_gencontrol`. It resolves the run-time dependencies in `package.xml`
through rosdep and records them as `ros:Depends`. Install-time dependencies
are therefore decided when the binary package is built, from the rosdep rules
that build was given.

Both read the rules a previous `rosdep update` fetched and fetch nothing
themselves. The platform is the one rosdep detects; `ROS_OS_OVERRIDE` replaces
it. The ROS distribution is `--rosdistro` or `ROS_DISTRO`.

```
rosdep update --rosdistro rolling
dyndeb-generate --rosdistro rolling --revision 1 .
apt-get build-dep -y ./
dpkg-buildpackage -us -uc
```

## What is generated

The result follows bloom's templates, so that a package is laid out like the
one build.ros2.org publishes: the same package name (`ros-<distro>-<name>`),
the same prefix (`/opt/ros/<distro>`), the same version
(`<version>-<revision><release code name>`) and the same build flags.

Tests are the difference. The generated `rules` runs the package's tests the
way colcon does (pytest for `ament_python`, ctest for the CMake build types)
and leaves the results as JUnit XML files in `$ROS_TEST_RESULTS_DIR` (by
default `.ros_test_results` in the source tree). For an `ament_cmake`
package these are the result files its tests write themselves.
A failing test does not stop the build; whoever runs the build reads the
results and decides. With `nocheck` in `DEB_BUILD_OPTIONS` no tests run.

## Limits

- **Build types.** `ament_python`, `ament_cmake` and `cmake`.
- **One binary package** per source package.
- **Not done:** group dependencies, the extra type-support build dependencies
  bloom gives interface packages, and rosdep keys to skip.
- **The tooling is not itself a package.** A source package built from the
  generated files needs `dh_rosdep` on the build machine, and its
  `Build-Depends` does not say so yet.

## Requirements

Python 3.10 or later, `catkin_pkg`, and rosdep for resolving keys. Building a
package needs `debhelper` 13 and `dh-python`.

## Tests

```
docker build -f ci/Dockerfile.test -t dyndeb-test .
docker run --rm dyndeb-test
```

## License

Apache-2.0. See [LICENSE](LICENSE).

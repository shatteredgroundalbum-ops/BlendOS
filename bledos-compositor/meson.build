project('bledos-compositor', 'c',
    version: '0.1.0',
    default_options: ['c_std=c11', 'warning_level=2'],
)

# Dependencies
wayland_server = dependency('wayland-server', version: '>=1.22')
wlroots = dependency('wlroots-0.19', version: '>=0.18')
json_c = dependency('libjson-c', version: '>=0.17')

src_files = files(
    'src/main.c',
)

executable('bledos-compositor',
    src_files,
    dependencies: [wayland_server, wlroots, json_c],
    install: true,
)

# Install socket directory
install_data(
    files(),
    install_dir: '/run/bledos',
    install_tag: 'runtime',
)
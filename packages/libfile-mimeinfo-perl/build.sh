# Pure-Perl MIME helpers and their complete non-core runtime closure. CPAN
# archives are fetched only at build time; installation never invokes CPAN.
TERMUX_PKG_HOMEPAGE=https://metacpan.org/dist/File-MimeInfo
TERMUX_PKG_DESCRIPTION="Perl MIME helpers with packaged runtime dependencies"
# Perl 5 dual license; retained verbatim in the distribution notices below.
TERMUX_PKG_LICENSE="custom" # Artistic-1.0-Perl OR GPL-1.0-or-later
TERMUX_PKG_LICENSE_FILE="README.md, URI-5.40/LICENSE, MIME-Base32-1.303/LICENSE, IPC-System-Simple-1.30/LICENSE, File-BaseDir-0.09/LICENSE, Encode-Locale-1.05/README, File-DesktopEntry-0.23/README.md"
TERMUX_PKG_MAINTAINER="@cnshing"
TERMUX_PKG_VERSION="0.37"
TERMUX_PKG_SRCURL=(
	"https://cpan.org/authors/id/M/MI/MICHIELB/File-MimeInfo-0.37.tar.gz"
	"https://cpan.org/authors/id/G/GA/GAAS/Encode-Locale-1.05.tar.gz"
	"https://cpan.org/authors/id/J/JK/JKEENAN/IPC-System-Simple-1.30.tar.gz"
	"https://cpan.org/authors/id/M/MI/MICHIELB/File-DesktopEntry-0.23.tar.gz"
	"https://cpan.org/authors/id/O/OA/OALDERS/URI-5.40.tar.gz"
	"https://cpan.org/authors/id/P/PL/PLICEASE/File-BaseDir-0.09.tar.gz"
	"https://cpan.org/authors/id/R/RE/REHSACK/MIME-Base32-1.303.tar.gz"
)
TERMUX_PKG_SHA256=(
	13e5bbfdd36da8af198913a94ab067312947239020906577b6bf938219b2d06b
	176fa02771f542a4efb1dbc2a4c928e8f4391bf4078473bd6040d8f11adb0ec1
	22e6f5222b505ee513058fdca35ab7a1eab80539b98e5ca4a923a70a8ae9ba9e
	63f95798d80b81ea8cea4848f342f26593c60f152dbd04d8981c846f979e6835
	ef5d2ef099a1a24a6e83ffe543de73337805d3d39c00b84fa205d725ad1a1b63
	6da6f7281562ac8f11ef1a3af6aedb51c41182b60f1f122ced0079efd92967d9
	ab21fa99130e33a0aff6cdb596f647e5e565d207d634ba2ef06bdbef50424e99
)
TERMUX_PKG_DEPENDS="perl, shared-mime-info"
TERMUX_PKG_PLATFORM_INDEPENDENT=true
TERMUX_PKG_BUILD_IN_SRC=true
TERMUX_PKG_AUTO_UPDATE=false

termux_step_configure() { :; }
termux_step_make() { :; }

termux_step_make_install() {
	# These modules are private to mimetype and mimeopen. A versioned site_perl
	# directory would stop working after a Termux Perl upgrade; global PERL5LIB
	# would also change module resolution for unrelated programs.
	local modules="$TERMUX_PREFIX/libexec/file-mimeinfo/perl5"
	local source distribution command
	install -d "$modules" "$TERMUX_PREFIX/bin"
	for source in "$TERMUX_PKG_SRCDIR" "$TERMUX_PKG_SRCDIR"/*/; do
		test -d "$source/lib" || continue
		cp -R "$source/lib/." "$modules/"
		distribution=$(basename "$source")
		test "$source" != "$TERMUX_PKG_SRCDIR" || distribution=File-MimeInfo-0.37
		# Retain each distribution's notices alongside its installed sources.
		install -d "$TERMUX_PREFIX/share/doc/$TERMUX_PKG_NAME/$distribution"
		for notice in "$source"/README* "$source"/LICENSE* "$source"/COPYING*; do
			test ! -f "$notice" || cp "$notice" "$TERMUX_PREFIX/share/doc/$TERMUX_PKG_NAME/$distribution/"
		done
	done
	for command in mimetype mimeopen; do
		sed -e "1c\\#!$TERMUX_PREFIX/bin/perl" \
			-e "2i\\use lib '$modules';" \
			"$TERMUX_PKG_SRCDIR/$command" > "$TERMUX_PREFIX/bin/$command"
		chmod 755 "$TERMUX_PREFIX/bin/$command"
	done
}

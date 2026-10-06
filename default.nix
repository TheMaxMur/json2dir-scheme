{ lib, stdenvNoCC, guile, python3 }:
stdenvNoCC.mkDerivation {
  pname = "json2dir-scheme";
  version = "0.1.0";
  src = lib.cleanSource ./.;

  nativeBuildInputs = [ guile ];
  nativeCheckInputs = [ python3 ];
  dontBuild = true;
  doCheck = true;
  checkPhase = ''
    runHook preCheck
    make test
    runHook postCheck
  '';
  installPhase = ''
    runHook preInstall
    make install PREFIX="$out" GUILE="${guile}/bin/guile"
    runHook postInstall
  '';

  meta = {
    description = "Convert JSON objects into directory trees, implemented in Scheme";
    license = lib.licenses.isc;
    platforms = lib.platforms.linux ++ lib.platforms.darwin;
    mainProgram = "json2dir";
  };
}

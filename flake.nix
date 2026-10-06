{
  description = "json2dir in Guile Scheme";
  inputs.nixpkgs.url = "https://flakehub.com/f/DeterminateSystems/nixpkgs-weekly/0.1";

  outputs = { self, nixpkgs }:
    let
      systems = [ "aarch64-darwin" "x86_64-darwin" "aarch64-linux" "x86_64-linux" ];
      eachSystem = nixpkgs.lib.genAttrs systems;
    in {
      packages = eachSystem (system:
        let pkgs = import nixpkgs { inherit system; };
        in {
          default = pkgs.callPackage ./default.nix {};
          json2dir = self.packages.${system}.default;
        });
      apps = eachSystem (system: {
        default = {
          type = "app";
          program = "${self.packages.${system}.default}/bin/json2dir";
        };
      });
      checks = eachSystem (system: { default = self.packages.${system}.default; });
      devShells = eachSystem (system:
        let pkgs = import nixpkgs { inherit system; };
        in { default = pkgs.mkShellNoCC { packages = [ pkgs.guile pkgs.python3 ]; }; });
    };
}

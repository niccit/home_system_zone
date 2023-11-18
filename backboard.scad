// SPDX-License-Identifier: MIT

// Mounting board for the new alarm system

// Show item
mounting=false;
siren=false;
battery=true;

board_length=177.8;
board_width=203.2;
board_height=5;

if (mounting == true) {
    // The replacement mounting board
    cube([board_length, board_width, board_height], center=true);
}

if (siren == true) {
    // Show the siren board - no CAD file available
    cube([105.73, 55.09, 1.5]);
}

if (battery == true) {
    difference() {
        cube([37.5, 62.5, 6.5], center=true);
        translate([0, 0.5, .5])
            cube([37.25, 62.25, 6.25], center=true);

    }
}




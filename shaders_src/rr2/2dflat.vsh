//
//  2Dflat.vsh
//
//  Created by bend on 27/11/09.
//  Copyright Firemint 2009. All rights reserved.
//

//%precompile

// Inputs
// -----------------------------------
attribute vec3 a_Position;	//%attributeID MT_POS

uniform highp mat4 u_ModelToProj;

void main()
{
	gl_Position = u_ModelToProj * vec4( a_Position, 1.0 );
}


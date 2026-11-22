//
//  vertex_colour.vsh
//
//  Created by bend on 18/02/10.
//  Copyright Firemint 2009. All rights reserved.
//

//%precompile

const lowp float c_one = 1.0;

// ======================================================================
// Inputs
// ======================================================================

// Attributes
// ----------------------------------------------------------------------

attribute highp vec3 a_Position;		//%attributeID MT_POS
attribute highp vec4 a_Colour;			//%attributeID MT_COLOUR

varying lowp vec4 v_DiffuseColour;

// Uniforms
// ----------------------------------------------------------------------

// Transformation Matrices
uniform highp mat4 u_ModelToProj;

void main()
{
	// Position
	gl_Position = u_ModelToProj * vec4( a_Position, c_one );
	v_DiffuseColour = a_Colour;
}


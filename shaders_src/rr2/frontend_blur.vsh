//
//  2Dimage.vsh
//
//  Created by bend on 27/11/09.
//  Copyright Firemint 2009. All rights reserved.
//

//%0define PASS_THROUGH
//%1define BLUR_HORIZONTAL
//%1define BLUR_11
//%2define BLUR_VERTICAL
//%2define BLUR_11
//%3define BLUR_HORIZONTAL
//%3define BLUR_7
//%4define BLUR_VERTICAL
//%4define BLUR_7
//%5define BLUR_HORIZONTAL
//%5define BLUR_5
//%6define BLUR_VERTICAL
//%6define BLUR_5
//%7define BLUR_HORIZONTAL
//%7define BLUR_3
//%8define BLUR_VERTICAL
//%8define BLUR_3
//%9define BLUR_HORIZONTAL
//%9define BLUR_2
//%10define BLUR_VERTICAL
//%10define BLUR_2

//////////////////////////////////////

//%feature PASS_THROUGH
//%feature BLUR_HORIZONTAL
//%feature BLUR_VERTICAL
//%feature BLUR_2
//%feature BLUR_3
//%feature BLUR_5
//%feature BLUR_7
//%feature BLUR_11

//%precompile PASS_THROUGH
//%precompile BLUR_2, BLUR_HORIZONTAL
//%precompile BLUR_2, BLUR_VERTICAL
//%precompile BLUR_3, BLUR_HORIZONTAL
//%precompile BLUR_3, BLUR_VERTICAL
//%precompile BLUR_5, BLUR_HORIZONTAL
//%precompile BLUR_5, BLUR_VERTICAL
//%precompile BLUR_7, BLUR_HORIZONTAL
//%precompile BLUR_7, BLUR_VERTICAL
//%precompile BLUR_11, BLUR_HORIZONTAL
//%precompile BLUR_11, BLUR_VERTICAL


const float c_zero = 0.0;
const float c_one = 1.0;

// Inputs
// -----------------------------------
attribute vec3 a_Position;	//%attributeID MT_POS
uniform mat4 u_ModelToProj;

attribute vec2 a_TexCoord0;	//%attributeID MT_UV_0
uniform mat3 u_TexMatrix0;

// Outputs
// -----------------------------------
varying highp vec2 v_TexCoord;

void main()
{
	v_TexCoord = (u_TexMatrix0 * vec3( a_TexCoord0, 1.0 )).xy;
	gl_Position = u_ModelToProj * vec4( a_Position, c_one );
}


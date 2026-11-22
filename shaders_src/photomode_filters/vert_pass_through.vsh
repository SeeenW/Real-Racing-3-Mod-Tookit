//
//  vert_pass_through.vsh
//
//  Created by bend on 06/09/13.
//  Copyright EA 2013. All rights reserved.
//

//%0define NO_FRAMEBUFFER_FETCH
//%1define FRAMEBUFFER_FETCH

////////////////////////////////

//%feature FRAMEBUFFER_FETCH
//%precompile FRAMEBUFFER_FETCH
//%precompile

#if defined(FRAMEBUFFER_FETCH)

// Framebuffer fetch extension
// ==============================================================
attribute vec3 a_Position;	//%attributeID MT_POS

uniform mat4 u_ModelToProj;

void main()
{
	gl_Position = u_ModelToProj * vec4( a_Position, 1.0 );
}

#else

// Simple pass through shader
// ==============================================================
attribute vec3 a_Position;	//%attributeID MT_POS
attribute vec2 a_TexCoord0;	//%attributeID MT_UV_0

uniform highp mat4 u_ModelToProj;
uniform highp mat3 u_TexMatrix0;
varying highp vec2 v_TexCoord;

void main()
{
	v_TexCoord = (u_TexMatrix0 * vec3( a_TexCoord0, 1.0 )).xy;
	//v_TexCoord = a_TexCoord0;
	gl_Position = u_ModelToProj * vec4( a_Position, 1.0 );
}

#endif


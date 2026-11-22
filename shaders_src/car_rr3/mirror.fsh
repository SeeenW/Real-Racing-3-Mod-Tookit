//
//  mirror.fsh
//
//  Created by Patrick on 09/08/12.
//  Copyright Electronic Arts 2012. All rights reserved.
//

precision mediump float;

// Texture samplers
uniform lowp samplerCube s_cubeMap;			// Cube map

uniform lowp vec3 u_MirrorTint;

// Vertex shader outputs
varying mediump vec3 v_CubeRay;

void main()
{
	// Cubemap reflection
	lowp vec3 cubeHighRes = textureCube( s_cubeMap, v_CubeRay ).rgb;
	cubeHighRes *= u_MirrorTint;
	gl_FragColor = vec4( cubeHighRes, 1.0 );
	//gl_FragColor = vec4( 1.0, 1.0, 0.0, 1.0 );
}


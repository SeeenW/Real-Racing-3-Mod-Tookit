//
//  windscreen_cracks.fsh
//
//  Created by vchau on 15/05/12.
//  Copyright Firemint 2012. All rights reserved.
//
//  Uses luminousity of the texture as the transparency mask.
//%include utility.xsh

#ifndef ENABLE_SHADER_FEATURES
	#ifndef DONT_USE_CAR_REFLECTION
		#ifndef CUBE_MAP
		#define CUBE_MAP
		#endif
	#endif
#endif

const lowp vec3 c_rgbToLuma = vec3(0.299, 0.587, 0.114);
const lowp float c_cubemultiplier = 1.3;

varying mediump vec2 v_TexCoord0;
uniform lowp sampler2D s_Texture0;

#ifdef CUBE_MAP
uniform lowp samplerCube s_cubeMap;			// Cube map
varying mediump vec3 v_CubeRay;
#endif

varying lowp vec3 v_DiffuseColour;

uniform mediump float mu_CrackBrightnessScale;
uniform mediump float mu_CrackMaskScale;

void main()
{
	lowp vec4 color = vec4( v_DiffuseColour, 1.0 );
	
	lowp vec4 texcolor = texture2DWithBias( s_Texture0, v_TexCoord0 );

#ifdef CUBE_MAP
	lowp vec3 cubeHighRes = textureCube( s_cubeMap, v_CubeRay ).rgb;
#endif
	
	mediump float mask = dot(texcolor.rgb, c_rgbToLuma) * mu_CrackMaskScale;

#ifdef CUBE_MAP
	gl_FragColor = vec4(cubeHighRes * mu_CrackBrightnessScale + v_DiffuseColour, mask);
#else
	gl_FragColor = vec4(v_DiffuseColour, mask);
#endif
	
	//gl_FragColor = vec4(v_DiffuseColour, 1.0);
}

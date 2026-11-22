//
//  2Dimage.fsh
//
//  Created by bend on 27/11/09.
//  Copyright Firemint 2009. All rights reserved.
//

uniform lowp vec4 u_CurrentColour;
uniform lowp sampler2D s_Texture0;
varying mediump vec2 v_TexCoord0;

void main()
{
	lowp vec4 color = u_CurrentColour;
	color *= texture2D( s_Texture0, v_TexCoord0 );

	lowp float luminance = color.r * 0.39 + color.g * 0.5 + color.b * 0.11;
	gl_FragColor = vec4(luminance, luminance, luminance, color.a);
}

